"""The MCP door's tools (CLAUDE.md §13.4, checklist T182-T190). Each is a thin read of, or call into, the Door, the
rail's sealed capsule store and RunView. None of them decides anything (D-005): verdicts come from the policy engine
through the rail, approvals only from a named human through Door.decide in their own door.

Dependencies are providers (callables), resolved on every call, so the engine can wire the Door after the MCP server
is built, and tests can hand in a Door over their own database.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import urlsplit

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, ConfigDict, Field

from contextrail.agentic.knowledge import KnowledgeHit, KnowledgeSearch
from contextrail.models import Evidence
from contextrail.rail.compile import wrap_untrusted
from contextrail.surfaces.door import Door

NOT_IN_KNOWLEDGE_BASE = "Not in the knowledge base: nothing curated supports an answer. Do not answer from memory."


class KnowledgeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    index: str             # which index answered
    hits: list[KnowledgeHit]
    note: str | None = None


def as_data(hit: KnowledgeHit) -> KnowledgeHit:
    """Untrusted text leaves this door fenced as data, exactly as it enters our own prompts (§11, P6)."""
    if hit.trust != "untrusted":
        return hit
    ev = Evidence(id=hit.id, kind="message" if hit.kind == "message" else "document",
                  source=urlsplit(hit.uri).scheme or "knowledge", uri=hit.uri, excerpt=hit.excerpt,
                  retrieved_at=datetime.now(UTC), trust="untrusted")
    return hit.model_copy(update={"excerpt": wrap_untrusted(ev)})


class ContextRailTools:
    def __init__(self, *, door: Callable[[], Door | None], knowledge: Callable[[], KnowledgeSearch | None]) -> None:
        self._door, self._knowledge = door, knowledge

    def door(self) -> Door:
        door = self._door()
        if door is None:
            raise ToolError("The engine has no door wired, so no run can be read or started.")
        return door

    def knowledge(self) -> KnowledgeSearch:
        index = self._knowledge()
        if index is None:
            raise ToolError("No knowledge index is wired.")
        return index

    # --- tools ----------------------------------------------------------------------------------------------

    async def search_enterprise_knowledge(
            self, query: Annotated[str, Field(min_length=2, max_length=500)],
            tags: list[str] | None = None,
            limit: Annotated[int, Field(ge=1, le=20)] = 5) -> KnowledgeResult:
        index = self.knowledge()
        hits = [as_data(h) for h in await index.search(query, tags=tags, limit=limit)]
        return KnowledgeResult(query=query, index=index.name, hits=hits,
                               note=None if hits else NOT_IN_KNOWLEDGE_BASE)

    def register(self, server: MCPServer) -> None:
        server.add_tool(
            self.search_enterprise_knowledge, name="search_enterprise_knowledge", title="Search enterprise knowledge",
            description=(
                "Search ContextRail's curated enterprise knowledge (written policy clauses, verbatim, with their "
                "source) by keywords or a policy id. Optional tags narrow the results. Every hit has an id to cite, "
                "a uri, and a trust label; untrusted text is returned fenced as data. An empty result means the "
                "knowledge base does not support an answer: say so, do not answer from memory. Read-only."))

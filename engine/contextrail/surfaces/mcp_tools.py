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
from uuid import UUID

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, ConfigDict, Field

from contextrail.agentic.knowledge import KnowledgeHit, KnowledgeSearch
from contextrail.audit import chain
from contextrail.capsule import DigestMismatch
from contextrail.models import CaseFile, Evidence
from contextrail.rail.compile import wrap_untrusted
from contextrail.rail.store import load_case
from contextrail.surfaces.door import Door
from contextrail.surfaces.presenter import RunView

NOT_IN_KNOWLEDGE_BASE = "Not in the knowledge base: nothing curated supports an answer. Do not answer from memory."

# A pinned person is a system-of-record ID (E-1042, W-8841, 50001234), never a name: IDs carry a digit and no
# spaces. The rail's lookup falls back to an exact-name search for anything else, so a name must stop here (P1).
SourceId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:-]*[0-9][A-Za-z0-9_.:-]*$", max_length=64,
                                description="A system-of-record ID such as E-1042 or W-8841, never a name.")]
# Who is asking, as their identity-map person id. POL-SOD-001 refuses every approval on a run nobody can
# attribute, so an MCP run must name its requester. The engine-token holder asserts it (as with the REST door);
# separation of duties then applies to that person in every door.
PersonId = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$",
                                description="The requester's ContextRail person id (identity map), e.g. p-anil.")]


class CapsuleHandle(BaseModel):
    """What an agent carries between tools: which run, and which sealed version of its case file (§13.4, X2)."""

    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class CompileResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    run_id: UUID
    capsule_handle: CapsuleHandle | None
    requested_by: str
    subject: str | None
    peer: str | None
    counts: dict[str, int]
    needs: list[dict]
    modes: dict[str, str]
    replay: bool
    next_step: str


def _next_step(view: RunView, sealed: bool) -> str:
    if view.status == "needs_input":
        return ("Ask the requester which person is meant (the candidates are listed in needs) and call "
                "compile_context_capsule again with the chosen subject_id or peer_id. Never choose one yourself.")
    if not sealed:
        return "No case file was sealed: this was a question, not a request. Use search_enterprise_knowledge."
    if view.status == "awaiting_approval":
        return ("Call check_policy_and_permissions with capsule_handle. Held actions wait for their named approver, "
                "who decides in their own door; these tools never approve.")
    return "Call check_policy_and_permissions with capsule_handle to read the verdicts and verification."


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

    async def sealed(self, run_id: UUID) -> CaseFile:
        """The run's case file, received by value and verified against its seal and the run's recorded digest.
        A failed seal halts the call and leaves an audit event, as the rail's own handoff does (P5)."""
        door = self.door()
        try:
            async with door.db.connection() as c:
                return await load_case(c, run_id)
        except LookupError as e:
            raise ToolError(f"Run {run_id} has no sealed case file.") from e
        except DigestMismatch as e:
            async with door.db.transaction() as c:
                await chain.append(c, run_id=run_id, event="capsule.digest_mismatch",
                                   payload={"expected": e.expected, "actual": e.actual, "channel": "mcp"})
            raise ToolError(f"Halted: the stored case file for run {run_id} does not match its seal. "
                            "Nothing was read from it; the mismatch is in the audit chain.") from e

    # --- tools ----------------------------------------------------------------------------------------------

    async def search_enterprise_knowledge(
            self, query: Annotated[str, Field(min_length=2, max_length=500)],
            tags: list[str] | None = None,
            limit: Annotated[int, Field(ge=1, le=20)] = 5) -> KnowledgeResult:
        index = self.knowledge()
        hits = [as_data(h) for h in await index.search(query, tags=tags, limit=limit)]
        return KnowledgeResult(query=query, index=index.name, hits=hits,
                               note=None if hits else NOT_IN_KNOWLEDGE_BASE)

    async def compile_context_capsule(
            self, request_text: Annotated[str, Field(min_length=3, max_length=4000)], requester: PersonId,
            subject_id: SourceId | None = None, peer_id: SourceId | None = None) -> CompileResult:
        door = self.door()
        if await door.resolve_actor("mcp", requester) is None:
            raise ToolError(f"Unknown requester {requester!r}: not in the identity map. A run nobody can attribute "
                            "could never be approved (POL-SOD-001), so none was started.")
        view = await door.start_run(request_text, channel="mcp", actor_external_id=requester,
                                    subject_id=subject_id, peer_id=peer_id)
        handle = None
        if view.capsule_digest is not None:
            case = await self.sealed(view.run_id)
            handle = CapsuleHandle(run_id=case.run_id, digest=case.digest)
        return CompileResult(status=view.status, run_id=view.run_id, capsule_handle=handle, requested_by=requester,
                             subject=view.subject, peer=view.peer, counts=view.counts, needs=view.needs,
                             modes=view.modes, replay=view.replay, next_step=_next_step(view, handle is not None))

    def register(self, server: MCPServer) -> None:
        server.add_tool(
            self.search_enterprise_knowledge, name="search_enterprise_knowledge", title="Search enterprise knowledge",
            description=(
                "Search ContextRail's curated enterprise knowledge (written policy clauses, verbatim, with their "
                "source) by keywords or a policy id. Optional tags narrow the results. Every hit has an id to cite, "
                "a uri, and a trust label; untrusted text is returned fenced as data. An empty result means the "
                "knowledge base does not support an answer: say so, do not answer from memory. Read-only."))
        server.add_tool(
            self.compile_context_capsule, name="compile_context_capsule", title="Compile a context capsule",
            description=(
                "Start a governed ContextRail run for a one-sentence request (for example 'Give Anil the same "
                "access as Rahul Mehta') and return its capsule handle {run_id, digest}: the sealed case file of "
                "the subject fetched by ID, evidence, constraints and every proposed action with its verdict. "
                "requester is the person asking (identity-map person id, e.g. p-anil); they can never approve "
                "their own request. "
                "Pass subject_id / peer_id only as system-of-record IDs, never names. If a name matches more "
                "than one person the result is needs_input with the candidates: ask, never guess. This starts "
                "the rail: allowed actions are carried out and verified, held actions are sent to their named "
                "approvers, refusals are final."))

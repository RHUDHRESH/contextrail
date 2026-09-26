"""Fake model clients for retrieval-grounded answers. Shaped like contextrail.llm.router.Router.call and its
LLMResponse (sec/H-llm): keyword-only call(), a reply with `.label` and `.tool_input(name)`. No network, ever."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FakeReply:
    tool: dict | None
    label: str = "llm:T1"

    def tool_input(self, name: str) -> dict | None:
        return self.tool if name == "grounded_answer" else None


@dataclass
class FakeModel:
    """Answers with a fixed tool input, or a function of the request; records every call."""

    answer: dict | None = None
    respond: object = None          # callable(request) -> dict, overrides `answer`
    raises: Exception | None = None
    calls: list[dict] = field(default_factory=list)

    async def call(self, **request) -> FakeReply:
        self.calls.append(request)
        if self.raises:
            raise self.raises
        return FakeReply(self.respond(request) if callable(self.respond) else self.answer)


def cite_all(request: dict) -> dict:
    """A well-behaved model: answers and cites every chunk id it was given."""
    import re

    ids = re.findall(r'<chunk id="([^"]+)"', request["messages"][0]["content"])
    return {"answer": "From the chunks.", "cited_chunk_ids": ids, "supported": True}

"""A question can select bounded read tools, but model prose never becomes an answer or an action."""

from decimal import Decimal
from uuid import uuid4

import pytest

from contextrail.llm.question_agent import NO_SUPPORT, ReadEvidence, ReadOnlyQuestionAgent
from contextrail.llm.router import HAIKU_DIRECT_ID, LLMResponse


def reply(*, name=None, arguments=None, cost="0.001", text="Invented answer with no citation"):
    content = ([{"type": "tool_use", "id": "tool-1", "name": name, "input": arguments or {}}]
               if name else [{"type": "text", "text": text}])
    return LLMResponse(tier="T1", model=HAIKU_DIRECT_ID, content=content,
                       stop_reason="tool_use" if name else "end_turn", cost_usd=Decimal(cost))


class Router:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    async def call(self, **kwargs):
        self.calls.append(kwargs)
        return self.replies.pop(0)


class Tools:
    def __init__(self, *, supported=True):
        self.calls = []
        self.supported = supported

    async def search_knowledge(self, query, *, actor_id):
        self.calls.append(("search", query, actor_id))
        return ReadEvidence(text="Policy §4 requires a named Security reviewer.", citations=["okf:policy:4"]
                            if self.supported else [], supported=self.supported, kind="knowledge")

    async def run_status(self, run_id, *, actor_id):
        self.calls.append(("status", run_id, actor_id))
        return ReadEvidence(text="Your run is awaiting Dana.", citations=["audit:42"],
                            supported=True, kind="run")

    async def my_runs(self, limit, *, actor_id):
        self.calls.append(("runs", limit, actor_id))
        return ReadEvidence(text="You have one run.", citations=["audit:5"], supported=True, kind="run")

    async def precedents(self, rule_id, *, actor_id):
        self.calls.append(("precedents", rule_id, actor_id))
        return ReadEvidence(text="One prior approval.", citations=["audit:9"],
                            supported=True, kind="precedent")


@pytest.mark.asyncio
async def test_model_selects_a_read_tool_but_only_cited_tool_text_reaches_the_user():
    router = Router(reply(name="search_knowledge", arguments={"query": "security reviewer"}))
    tools = Tools()
    result = await ReadOnlyQuestionAgent(router, tools).ask("Who reviews production access?", actor_id="p-anil")
    assert result.text == "Policy §4 requires a named Security reviewer."
    assert result.citations == ["okf:policy:4"] and result.author == "knowledge"
    assert result.tools_used == ["search_knowledge"] and tools.calls == [("search", "security reviewer", "p-anil")]
    assert router.calls[0]["max_tokens"] == 250 and router.calls[0]["stage"] == "question.read"


@pytest.mark.asyncio
async def test_free_model_prose_is_not_a_grounded_answer():
    result = await ReadOnlyQuestionAgent(Router(reply()), Tools()).ask("What happened?", actor_id="p-anil")
    assert result.text == NO_SUPPORT and result.citations == [] and result.tools_used == []


@pytest.mark.asyncio
async def test_unknown_or_malformed_tool_cannot_execute():
    for model_reply in (reply(name="execute_and_verify", arguments={"run_id": str(uuid4())}),
                        reply(name="run_status", arguments={"run_id": "not-a-uuid"})):
        tools = Tools()
        result = await ReadOnlyQuestionAgent(Router(model_reply), tools).ask("Status?", actor_id="p-anil")
        assert result.text == NO_SUPPORT and tools.calls == []


@pytest.mark.asyncio
async def test_private_run_tools_require_an_actor_and_never_read_anonymous_runs():
    tools = Tools()
    result = await ReadOnlyQuestionAgent(Router(reply(name="run_status", arguments={"run_id": str(uuid4())})),
                                         tools).ask("Status?", actor_id=None)
    assert result.text == NO_SUPPORT and tools.calls == []


@pytest.mark.asyncio
async def test_unsupported_evidence_can_trigger_one_more_read_then_stops_at_step_limit():
    router = Router(reply(name="search_knowledge", arguments={"query": "no such policy"}),
                    reply(name="my_runs", arguments={"limit": 2}),
                    reply(name="precedents", arguments={"rule_id": "POL-CTR-001"}))
    tools = Tools(supported=False)
    result = await ReadOnlyQuestionAgent(router, tools, max_steps=2).ask("What else?", actor_id="p-anil")
    assert result.text == "You have one run." and len(router.calls) == 2
    assert result.tools_used == ["search_knowledge", "my_runs"]
    assert router.calls[1]["messages"][-1]["content"][0]["type"] == "tool_result"


@pytest.mark.asyncio
async def test_cost_cap_prevents_another_model_call():
    router = Router(reply(name="search_knowledge", arguments={"query": "no such policy"}, cost="0.02"))
    result = await ReadOnlyQuestionAgent(router, Tools(supported=False)).ask("No evidence?", actor_id="p-anil")
    assert result.text == NO_SUPPORT and len(router.calls) == 1


def test_limits_cannot_be_raised_past_policy():
    with pytest.raises(ValueError):
        ReadOnlyQuestionAgent(Router(), Tools(), max_steps=5)
    with pytest.raises(ValueError):
        ReadOnlyQuestionAgent(Router(), Tools(), max_cost_usd=Decimal("0.06"))

"""Intent extraction keeps model output to validated, verbatim mentions; identity lookup remains code."""

from uuid import uuid4

import pytest
from llm_fakes import FakeClient, config, make_router, message

from contextrail.connectors.fixture import FixtureHRIS
from contextrail.connectors.state import FixtureState
from contextrail.llm.adapters import LLMIntentExtractor
from contextrail.llm.router import LLMResponse
from contextrail.rail.discover import discover
from contextrail.rail.email_intake import untrusted_email

REQUEST = "Give Anil the same access as Rahul"
INTENT = {"intent": "access.same_as_peer", "kind": "request", "subject_mention": "Anil",
          "peer_mention": "Rahul", "dates": []}


def _extractor(answer: dict, *, text: str | None = None):
    client = FakeClient(message(text, tool="extract_intent", tool_input=answer))
    return LLMIntentExtractor(make_router(config(keys="A"), {"T1": client})), client


async def test_forced_validated_tool_returns_mentions_with_the_model_label():
    extractor, client = _extractor(INTENT)
    result = await extractor.extract(REQUEST)
    assert (result.intent, result.kind, result.subject_mention, result.peer_mention) == (
        "access.same_as_peer", "request", "Anil", "Rahul")
    assert result.extractor == "llm:T1"
    assert not hasattr(result, "subject") and not hasattr(result, "source_id")
    sent = client.calls[0]
    assert sent["tool_choice"] == {"type": "tool", "name": "extract_intent"}
    assert sent["tools"][0]["input_schema"]["additionalProperties"] is False
    assert "verdict" not in sent["tools"][0]["input_schema"]["properties"]
    assert sent["max_tokens"] == 300 and sent["extra_body"] == {"temperature": 0}
    assert '<untrusted source="request">' in sent["messages"][0]["content"]


@pytest.mark.parametrize("text,answer,kind", [
    ("What happened to my request?", {"intent": "query", "kind": "query"}, "query"),
    ("Approve", {"intent": "approval_reply", "kind": "approval_reply"}, "approval_reply"),
])
async def test_query_and_approval_reply_are_classified_without_a_resolved_person(text, answer, kind):
    extractor, _ = _extractor(answer)
    result = await extractor.extract(text)
    assert result.kind == kind and result.extractor == "llm:T1"
    assert result.subject_mention is None and result.peer_mention is None


@pytest.fixture
def hris(tmp_path):
    state = FixtureState("hris", directory=tmp_path)
    state.reset()
    return FixtureHRIS(state)


async def test_model_mentions_still_go_through_exact_lookup_and_ambiguity(hris):
    extractor, _ = _extractor(INTENT)
    found = await discover(REQUEST, extractor, hris)
    assert found.status == "needs_input" and found.subject.source_id == "E-1042"
    assert found.peer is None and {c.source_id for c in found.needs[0].candidates} == {"E-0007", "E-0415"}


async def test_a_fabricated_id_falls_back_before_identity_resolution(hris):
    extractor, _ = _extractor({**INTENT, "peer_mention": "E-0007"})
    found = await discover(REQUEST, extractor, hris)
    assert found.status == "needs_input" and found.intent.extractor == "heuristic"
    assert found.intent.peer_mention == "Rahul" and found.peer is None


@pytest.mark.parametrize("answer", [
    {**INTENT, "verdict": "ALLOW"},
    {**INTENT, "kind": "query"},
    {**INTENT, "intent": "grant_everything"},
    {**INTENT, "dates": ["tomorrow"]},
])
async def test_invalid_or_invented_fields_fall_back_to_heuristic(answer):
    extractor, _ = _extractor(answer)
    result = await extractor.extract(REQUEST)
    assert result.extractor == "heuristic" and result.peer_mention == "Rahul"


@pytest.mark.parametrize("stop_reason,tool", [("end_turn", None), ("max_tokens", "extract_intent")])
async def test_missing_or_truncated_tool_output_falls_back(stop_reason, tool):
    client = FakeClient(message("Anil", tool=tool, tool_input=INTENT, stop_reason=stop_reason))
    extractor = LLMIntentExtractor(make_router(config(keys="A"), {"T1": client}))
    assert (await extractor.extract(REQUEST)).extractor == "heuristic"


async def test_no_model_tier_falls_back_without_claiming_a_live_answer():
    extractor = LLMIntentExtractor(make_router(config(keys=""), {}))
    result = await extractor.extract(REQUEST)
    assert result.extractor == "heuristic" and result.peer_mention == "Rahul"


async def test_email_input_remains_fenced_and_mentions_are_checked_in_its_body():
    extractor, client = _extractor(INTENT)
    result = await extractor.extract(untrusted_email(REQUEST))
    assert result.extractor == "llm:T1"
    sent = client.calls[0]["messages"][0]["content"]
    assert "&lt;untrusted source=" in sent and "Give Anil the same access as Rahul" in sent


async def test_run_id_is_passed_to_router_for_per_run_budget_and_replay_is_labelled():
    run_id = uuid4()

    class StubRouter:
        def __init__(self):
            self.kwargs = None

        async def call(self, **kwargs):
            self.kwargs = kwargs
            return LLMResponse(tier="T4", model="claude-haiku-4-5-20251001", replay=True,
                               stop_reason="tool_use", content=[{"type": "tool_use", "name": "extract_intent",
                                                                 "input": INTENT}])

    router = StubRouter()
    result = await LLMIntentExtractor(router, run_id=run_id).extract(REQUEST)
    assert result.extractor == "replay"
    assert router.kwargs["run_id"] == run_id and router.kwargs["stage"] == "discover"

"""T203: a registered approver hears only the items awaiting them, confirms one by voice, then decides it with DTMF
1 (approve) or 2 (refuse) through the engine's decision endpoint. High-risk items are never decided by phone: they
need a tap in Slack or Teams (CLAUDE.md §13.3 item 7, §16). The engine checks everything else (D-005)."""

import pytest

from dialogue import Dialogue
from engine_client import Caller, EngineClient, RowView
from flows import high_risk
from languages import configure
from llm import Conversation
from tests.fake_engine import HASH_A, HASH_B, HASH_C, TOKEN, FakeEngine, row, run_view
from tests.fakes import FakeAnthropic

DANA_PHONE = "+919990000150"
FIGMA = row("a-figma", label="Figma professional seat", rule_id="POL-ACC-005", params_hash=HASH_A)
REPO = row("a-repo", label="GitHub read on northbeam/payments-core", rule_id="POL-ACC-004",
           clause="Production-tagged repositories need Security approval.", params_hash=HASH_B)
MEERAS = row("a-pii", label="Raw PII view", rule_id="POL-DAT-001", approver_id="p-meera",
             approver_name="Meera Iyer", params_hash=HASH_C)


def make():
    engine = FakeEngine()
    view = run_view(rows=[FIGMA, REPO, MEERAS, row("a-slack", label="Slack", verdict="ALLOW", state="verified",
                                                   approver_id=None, rule_id="POL-ACC-001")])
    engine.pending["p-dana"] = [view]
    fake = FakeAnthropic(error=RuntimeError("the model must not be called in the approver flow"))
    d = Dialogue(languages=configure("en-IN"), llm=Conversation(fake),
                 engine=EngineClient("http://engine.test", TOKEN, transport=engine.transport()),
                 caller=Caller(person_id="p-dana", display_name="Dana Osei"), caller_phone=DANA_PHONE)
    return d, engine, view


def decisions(engine):
    return [r for r in engine.requests if r.url.path.endswith("/decisions")]


async def test_only_items_awaiting_this_caller_are_offered_and_nothing_is_decided_by_voice_alone():
    d, engine, _ = make()
    turn = await d.on_utterance("approve my pending items")
    assert engine.body(0) == {"channel": "voice", "actor_external_id": DANA_PHONE}
    assert turn.say == [d.line("pending_count").format(n=2),
                        d.line("item").format(i=1, label=FIGMA["label"], subject="Anil Kumar", rule="POL-ACC-005"),
                        d.line("decide_this")]
    assert turn.control is None and decisions(engine) == []


async def test_a_spoken_yes_asks_for_a_key_and_leaves_the_stream_for_dtmf():
    d, engine, _ = make()
    await d.on_utterance("approve my pending items")
    turn = await d.on_utterance("yes")
    assert turn.say == [d.line("press_keys")] and turn.control == "gather_dtmf"
    assert d.take_next_step() == "gather_dtmf" and d.take_next_step() is None
    assert decisions(engine) == []


@pytest.mark.parametrize(("key", "decision"), [("1", "approved"), ("2", "refused")])
async def test_dtmf_1_approves_and_2_refuses_through_the_engine_bound_to_params_hash(key, decision):
    d, engine, view = make()
    await d.on_utterance("approve my pending items")
    await d.on_utterance("yes")
    turn = await d.on_dtmf(key)
    [req] = decisions(engine)
    assert req.url.path == f"/v1/runs/{view['run_id']}/decisions"
    assert engine.body() == {"action_id": "a-figma", "params_hash": HASH_A, "channel": "voice",
                             "actor_external_id": DANA_PHONE, "decision": decision, "reason": None}
    assert turn.say[0] == d.line(f"decided_{decision}")
    assert turn.say[1] == d.line("item").format(i=2, label=REPO["label"], subject="Anil Kumar", rule="POL-ACC-004")


async def test_the_resumed_stream_speaks_the_outcome_instead_of_the_opening():
    d, _, _ = make()
    await d.on_utterance("approve my pending items")
    await d.on_utterance("yes")
    decided = await d.on_dtmf("1")
    assert (await d.opening()).say == decided.say
    assert (await d.opening()).say == [d.disclosed("menu")]  # only once


async def test_a_high_risk_item_is_not_decidable_by_phone():
    d, engine, _ = make()
    await d.on_utterance("approve my pending items")
    await d.on_utterance("next")                     # skip the Figma seat
    turn = await d.on_utterance("yes")               # the production-tagged repository
    assert turn.say == [d.line("high_risk"), d.line("no_more")] and turn.control is None
    assert (await d.on_dtmf("1")).say == []  # no key capture was asked for: nothing to decide
    assert decisions(engine) == []


async def test_no_key_or_another_key_decides_nothing():
    d, engine, _ = make()
    await d.on_utterance("approve my pending items")
    await d.on_utterance("yes")
    turn = await d.on_dtmf("")
    assert turn.say[0] == d.line("no_key") and decisions(engine) == []


async def test_a_duplicate_dtmf_callback_decides_once():
    d, engine, _ = make()
    await d.on_utterance("approve my pending items")
    await d.on_utterance("yes")
    decided = await d.on_dtmf("1")
    await d.on_dtmf("1")
    assert len(decisions(engine)) == 1
    assert (await d.opening()).say == decided.say


@pytest.mark.parametrize(("result", "expected"), [
    ({"outcome": "already_decided", "decided_by": "p-meera", "decided_channel": "teams", "reason": "already approved"},
     "already_decided"),
    ({"outcome": "already_decided", "decided_by": "p-dana", "decided_channel": "slack", "reason": "already refused"},
     "already_yours"),
    ({"outcome": "rejected", "reason": "this card is out of date: the action's parameters changed"}, "rejected"),
])
async def test_the_engines_outcome_is_what_the_caller_hears(result, expected):
    d, engine, _ = make()
    engine.decision = {"outcome": "recorded", "reason": None, "rule_id": None, "decided_by": None,
                       "decided_channel": None, "view": None} | result
    await d.on_utterance("approve my pending items")
    await d.on_utterance("yes")
    said = (await d.on_dtmf("2")).say[0]
    if expected == "already_decided":
        assert said == d.line("already_decided").format(channel="teams")
    elif expected == "already_yours":
        assert said == d.line("already_yours")
    else:
        assert said == f"{d.line('rejected')} {result['reason']}"


async def test_nothing_waiting_is_said_plainly():
    d, engine, _ = make()
    engine.pending.clear()
    assert (await d.on_utterance("approve my pending items")).say == [d.line("nothing_pending")]


def _row(**kw) -> RowView:
    return RowView.model_validate(row("a", label=kw.pop("label", "Figma seat"), **kw))


@pytest.mark.parametrize(("r", "risky"), [
    (_row(rule_id="POL-ACC-005"), False),
    (_row(rule_id="POL-ACC-004"), True),                                     # production-tagged repository
    (_row(rule_id="POL-ACC-003", label="Admin on the billing console"), True),  # administrator rights
    (_row(rule_id="POL-EMG-001"), True), (_row(rule_id="POL-DAT-001"), True),
    (_row(rule_id="POL-ACC-005", label="Production dashboard seat"), True),  # anything naming production
])
def test_high_risk_means_production_admin_emergency_or_raw_pii(r, risky):
    assert high_risk(r) is risky

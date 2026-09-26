"""T201: a registered caller's request is read back word for word, started only after a spoken yes, and answered
with the run's reference and the engine's own counts. The model never touches the request (CLAUDE.md §13.3 item 5).
"""

import pytest

from dialogue import Dialogue
from engine_client import Caller, EngineClient
from intents import match_yes_no
from languages import configure
from llm import Conversation
from tests.fake_engine import TOKEN, FakeEngine
from tests.fakes import FakeAnthropic

ANIL_PHONE = "+919990000142"
REQUEST = "give Anil the same access as Rahul"


def make(code="en-IN"):
    engine = FakeEngine()
    fake = FakeAnthropic(error=RuntimeError("the model must not be called in the request flow"))
    d = Dialogue(languages=configure(code), llm=Conversation(fake),
                 engine=EngineClient("http://engine.test", TOKEN, transport=engine.transport()),
                 caller=Caller(person_id="p-anil", display_name="Anil Kumar"), caller_phone=ANIL_PHONE,
                 call_ref="call-uuid-7")
    return d, engine, fake


def runs_started(engine):
    return [r for r in engine.requests if (r.method, r.url.path) == ("POST", "/v1/runs")]


async def test_the_request_is_read_back_and_nothing_starts_before_yes():
    d, engine, _ = make()
    turn = await d.on_utterance(REQUEST)
    assert turn.say == [d.line("readback").format(text=REQUEST)]
    assert runs_started(engine) == []


async def test_yes_starts_one_run_with_the_callers_exact_words_and_speaks_the_reference():
    d, engine, fake = make()
    await d.on_utterance(REQUEST)
    turn = await d.on_utterance("yes, go ahead")
    assert len(runs_started(engine)) == 1
    assert engine.body() == {"request_text": REQUEST, "channel": "voice", "actor_external_id": ANIL_PHONE,
                             "source_ref": "call-uuid-7"}
    view = next(iter(engine.runs.values()))
    ref = " ".join(view["run_id"].replace("-", "")[:8].upper())
    assert turn.say[0] == d.line("started").format(ref=ref)
    assert d.line("st_awaiting_approval") in " ".join(turn.say)
    assert fake.messages.calls == []


async def test_no_cancels_and_starts_nothing():
    d, engine, _ = make()
    await d.on_utterance(REQUEST)
    turn = await d.on_utterance("no")
    assert turn.say == [d.line("cancelled")] and runs_started(engine) == []


async def test_an_unclear_answer_asks_again_and_keeps_the_request():
    d, engine, _ = make()
    await d.on_utterance(REQUEST)
    assert (await d.on_utterance("hmm maybe")).say == [d.line("yes_or_no")]
    await d.on_utterance("yes")
    assert len(runs_started(engine)) == 1 and engine.body()["request_text"] == REQUEST


async def test_asking_to_make_a_request_prompts_for_it_first():
    d, engine, _ = make()
    assert (await d.on_utterance("I want to make a new request")).say == [d.line("ask_request")]
    await d.on_utterance("Priya starts Monday, give her everything she needs")
    await d.on_utterance("yes")
    assert engine.body()["request_text"] == "Priya starts Monday, give her everything she needs"


async def test_an_unreachable_engine_is_said_plainly():
    d, engine, _ = make()
    await d.on_utterance(REQUEST)
    engine.fail_with = 503
    assert (await d.on_utterance("yes")).say == [d.line("engine_down")]


async def test_a_hindi_caller_confirms_in_hindi():
    d, engine, _ = make("hi-IN")
    said = "अनिल को राहुल जैसा एक्सेस दे दो"
    assert (await d.on_utterance(said)).say == [d.line("readback").format(text=said)]
    await d.on_utterance("हाँ जी")
    assert engine.body()["request_text"] == said


@pytest.mark.parametrize(("said", "answer"), [
    ("yes", True), ("yeah sure", True), ("हाँ", True), ("जी हां, ठीक है", True), ("ஆம்", True), ("சரி", True),
    ("ಹೌದು", True), ("no", False), ("नहीं", False), ("जी नहीं", False), ("இல்லை", False), ("ಬೇಡ", False),
    ("cancel it", False), ("hmm", None), ("nothing", None), ("", None)])
def test_yes_and_no_in_four_languages_with_no_winning_a_tie(said, answer):
    assert match_yes_no(said) is answer

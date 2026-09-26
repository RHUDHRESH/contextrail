"""T202: status and policy answers are the engine's words and nothing else: receipts and curated policy, never a
model's guess (CLAUDE.md §13.3 item 6). The model stays silent even when it is available."""

import pytest

from dialogue import Dialogue
from engine_client import Caller, EngineClient
from languages import configure
from llm import Conversation
from tests.fake_engine import TOKEN, FakeEngine
from tests.fakes import FakeAnthropic

ANIL_PHONE = "+919990000142"
FACT = ("Your request \"same as Rahul\" is awaiting approval: 15 done and verified, 2 waiting for Dana Osei, "
        "Meera Iyer, 1 refused: Production admin (POL-CTR-001).")


def make(*, registered=True, code="en-IN"):
    engine, fake = FakeEngine(), FakeAnthropic(["I think it was approved yesterday."])  # a guess it must never say
    engine.answer = {"text": FACT, "run_id": None, "citations": [41, 57]}
    who = {"caller": Caller(person_id="p-anil", display_name="Anil Kumar"), "caller_phone": ANIL_PHONE} \
        if registered else {}
    d = Dialogue(languages=configure(code), llm=Conversation(fake),
                 engine=EngineClient("http://engine.test", TOKEN, transport=engine.transport()), **who)
    return d, engine, fake


@pytest.mark.parametrize("question", ["what happened to my request?", "can contractors get production access?"])
async def test_the_answer_is_the_engines_text_verbatim_and_the_model_is_not_asked(question):
    d, engine, fake = make()
    turn = await d.on_utterance(question)
    assert turn.say == [d.line("from_records"), FACT]
    assert engine.body() == {"question": question, "channel": "voice", "actor_external_id": ANIL_PHONE}
    assert fake.messages.calls == []


async def test_an_unknown_caller_asks_policy_without_any_identity():
    d, engine, fake = make(registered=False)
    turn = await d.on_utterance("can contractors get production access?")
    assert turn.say == [d.line("from_records"), FACT]
    assert engine.body()["actor_external_id"] is None and fake.messages.calls == []


async def test_an_empty_engine_answer_is_not_filled_in():
    d, engine, fake = make()
    engine.answer = {"text": "  ", "run_id": None, "citations": []}
    assert (await d.on_utterance("what happened to my request?")).say == [d.line("no_answer")]
    assert fake.messages.calls == []


async def test_an_unreachable_engine_is_said_plainly():
    d, engine, fake = make()
    engine.fail_with = 500
    assert (await d.on_utterance("is it allowed to share the dashboard")).say == [d.line("engine_down")]
    assert fake.messages.calls == []


async def test_a_hindi_caller_hears_a_hindi_preface_and_the_engine_text_unchanged():
    d, _, _ = make(code="hi-IN")
    turn = await d.on_utterance("मेरे अनुरोध का क्या हुआ?")
    assert turn.say == [d.line("from_records"), FACT]

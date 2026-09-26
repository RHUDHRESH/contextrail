"""T198: the first sentence a caller hears, in every language, says they are talking to an AI and not a person
(CLAUDE.md §13.3 item 8). Switching language repeats it first, in the new language."""

import json

import pytest

import agent
from languages import SUPPORTED
from llm import Conversation
from tests.fake_sarvam import FakeSarvam
from tests.fakes import FakeAnthropic, FakeWS

# How each language says "AI" and "not a person", written out here independently of languages.py.
AI_WORDS = {"hi-IN": ("एआई", "इंसान नहीं"), "en-IN": ("AI", "not a person"),
            "ta-IN": ("AI", "மனிதர் அல்ல"), "kn-IN": ("AI", "ಮನುಷ್ಯನಲ್ಲ")}


@pytest.mark.parametrize("code", sorted(SUPPORTED))
def test_each_language_has_a_one_sentence_ai_disclosure(code):
    line = SUPPORTED[code].lines["disclosure"]
    ai, not_human = AI_WORDS[code]
    assert ai in line and not_human in line
    assert line.rstrip()[-1] in ".।" and not any(stop in line.rstrip()[:-1] for stop in ".।?!")


START = json.dumps({"event": "start", "start": {"callId": "call-1", "streamId": "stream-1"}})


@pytest.mark.parametrize("code", sorted(SUPPORTED))
async def test_the_first_words_of_every_call_are_the_disclosure(code):
    sarvam = FakeSarvam()
    s = agent.CallSession(FakeWS(), sarvam_transport=sarvam.transport(), lang=SUPPORTED[code],
                          llm=Conversation(FakeAnthropic()))
    await s.handle_message(START)
    assert sarvam.spoken()[0].startswith(SUPPORTED[code].lines["disclosure"])
    assert sarvam.tts[0]["target_language_code"] == code


async def test_switching_language_discloses_again_before_anything_else():
    sarvam = FakeSarvam(["Tamil"])
    s = agent.CallSession(FakeWS(), sarvam_transport=sarvam.transport())
    await s.handle_message(START)
    await s._process(b"\xff" * 1600)
    assert sarvam.tts[-1]["target_language_code"] == "ta-IN"
    assert sarvam.spoken()[-1].startswith(SUPPORTED["ta-IN"].lines["disclosure"])

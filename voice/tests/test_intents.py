"""T197: what the caller wants is routed to one of four door flows (new request, status, policy question, approve)
or to a person. Keywords decide first, in any of the four languages; Haiku is asked only when none match, and can
only pick from the same fixed list. Routing picks a flow; each flow still confirms before anything happens."""

import pytest

from dialogue import Dialogue
from intents import INTENTS, match_keywords, route
from languages import configure
from llm import Conversation
from tests.fakes import FakeAnthropic


@pytest.mark.parametrize(("said", "intent"), [
    ("give Anil the same access as Rahul", "request"),
    ("Priya starts Monday, give her everything she needs", "request"),
    ("अनिल को राहुल जैसा एक्सेस दे दो", "request"),
    ("அனிலுக்கு ராகுல் போன்ற அணுகல் கொடுங்கள்", "request"),
    ("ಅನಿಲ್‌ಗೆ ರಾಹುಲ್ ಅವರಂತೆ ಪ್ರವೇಶ ಕೊಡಿ", "request"),
    ("what happened to my request?", "status"),
    ("what happened to my access request", "status"),
    ("मेरे अनुरोध का क्या हुआ?", "status"),
    ("என் கோரிக்கையின் நிலை என்ன?", "status"),
    ("ನನ್ನ ವಿನಂತಿಯ ಸ್ಥಿತಿ ಏನು?", "status"),
    ("can contractors get production access?", "policy"),
    ("is it allowed to share the analytics dashboard", "policy"),
    ("क्या कॉन्ट्रैक्टर को प्रोडक्शन एक्सेस मिल सकता है?", "policy"),
    ("ஒப்பந்ததாரர்களுக்கு production அணுகல் கிடைக்குமா?", "policy"),
    ("ಗುತ್ತಿಗೆದಾರರಿಗೆ production ಪ್ರವೇಶ ಸಿಗುತ್ತದೆಯೇ?", "policy"),
    ("I want to approve my pending items", "approve"),
    ("मेरे पेंडिंग अप्रूवल सुनाइए", "approve"),
    ("ஒப்புதல் கொடுக்க வேண்டியவை", "approve"),
    ("ನನ್ನ ಅನುಮೋದನೆಗಾಗಿ ಕಾಯುತ್ತಿರುವವು", "approve"),
    ("let me talk to a human", "human"),
    ("मुझे किसी इंसान से बात करनी है", "human"),
    ("ஒரு மனிதரிடம் பேச வேண்டும்", "human"),
    ("ಒಬ್ಬ ಮನುಷ್ಯನ ಜೊತೆ ಮಾತನಾಡಬೇಕು", "human"),
])
def test_keywords_route_in_every_language(said, intent):
    assert match_keywords(said) == intent


@pytest.mark.parametrize("said", ["I need personal GitHub access for the SDK repo", "hmm", ""])
def test_near_misses_do_not_match(said):
    assert match_keywords(said) in (None, "request")
    assert match_keywords(said) != "human"  # "personal" is not "person"


async def test_haiku_is_asked_only_when_no_keyword_matches_and_can_only_pick_from_the_list():
    fake = FakeAnthropic([{"intent": "status"}])
    llm = Conversation(fake)
    assert await route("give Anil the same access as Rahul", llm) == "request"
    assert fake.messages.calls == []
    assert await route("bataiye woh kaam hua ki nahi", llm) == "status"
    call = fake.messages.calls[0]
    assert call["tool_choice"] == {"type": "tool", "name": "route_call"}
    assert call["tools"][0]["input_schema"]["properties"]["intent"]["enum"] == list(INTENTS)
    assert call["extra_body"] == {"temperature": 0} and call["max_tokens"] <= 100
    assert call["messages"][0]["content"].startswith('<untrusted source="voice-transcript">')


async def test_an_answer_outside_the_list_or_no_model_is_unclear():
    assert await route("bataiye woh kaam hua ki nahi", Conversation(FakeAnthropic([{"intent": "approve_all"}]))) \
        == "unclear"
    assert await route("bataiye woh kaam hua ki nahi", Conversation(None)) == "unclear"


class Recorder:
    def __init__(self):
        self.calls = []

    def flow(self, name):
        async def run(dialogue, text):
            self.calls.append((name, text))
            return [f"<{name}>"]
        return run


def _dialogue(fake=None, rec=None):
    rec = rec or Recorder()
    flows = {name: rec.flow(name) for name in ("request", "status", "policy", "approve", "human")}
    return Dialogue(languages=configure("hi-IN"), llm=Conversation(fake or FakeAnthropic()), flows=flows), rec


async def test_the_dialogue_dispatches_each_intent_to_its_flow():
    d, rec = _dialogue()
    for said, flow in [("approve my pending items", "approve"), ("what happened to my request", "status"),
                       ("can contractors get production access", "policy"), ("talk to a human", "human"),
                       ("give Anil the same access as Rahul", "request")]:
        turn = await d.on_utterance(said)
        assert rec.calls[-1] == (flow, said) and turn.say == [f"<{flow}>"]


async def test_unclear_speech_gets_a_conversational_reply_that_decides_nothing():
    reply = "Aap nayi request, status, policy ya approval ke baare mein pooch sakte hain."
    d, rec = _dialogue(FakeAnthropic([{"intent": "unclear"}, reply]))
    turn = await d.on_utterance("hmm haan ji")
    assert rec.calls == [] and turn.say == [reply]


async def test_without_a_model_unclear_speech_hears_the_apology_and_the_menu():
    d, rec = _dialogue(FakeAnthropic(error=RuntimeError("never called")))
    d.llm = Conversation(None)
    turn = await d.on_utterance("hmm haan ji")
    assert rec.calls == [] and turn.say == [f"{d.lang.lines['fallback']} {d.lang.lines['menu']}"]


async def test_the_opening_is_the_disclosure_then_the_menu():
    d, _ = _dialogue()
    turn = await d.opening()
    assert turn.say[0].startswith(d.lang.lines["disclosure"]) and turn.say[0].endswith(d.lang.lines["menu"])

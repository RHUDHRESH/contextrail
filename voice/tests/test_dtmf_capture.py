"""T203 on the wire: Vobiz does not send key presses on the media WebSocket (its stream events are start, media,
playedStream, clearedAudio), so the door captures DTMF the documented way. It finishes speaking, stops the stream,
Vobiz runs the <Redirect> after <Stream>, the door answers with a <Gather inputType="dtmf">, the key goes to the
engine's decision endpoint, and a new stream resumes the same conversation.
XML shapes follow vobiz-ai/Vobiz-IVR-XML-Python and Agent-Skills vobiz-voice-xml."""

import asyncio
import json
import re

import pytest

import agent
from dialogue import Dialogue
from engine_client import Caller
from flows import Turn
from languages import configure
from llm import Conversation
from tests.fake_sarvam import FakeSarvam
from tests.fakes import FakeAnthropic, FakeWS
from tests.test_approver_flow import FIGMA, HASH_A
from tests.test_caller_id import DANA_RAW, PUBLIC, START, World, signed

NESTED_START = json.dumps({"sequenceNumber": 0, "event": "start",
                           "start": {"callId": "call-9", "streamId": "stream-9", "tracks": ["inbound"],
                                     "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000}}})


async def test_the_start_event_ids_are_read_from_the_nested_start_object():
    s = agent.CallSession(FakeWS(), sarvam_transport=FakeSarvam().transport())
    await s.handle_message(NESTED_START)
    assert (s.stream_id, s.call_id) == ("stream-9", "call-9")


def _session_with_control(ws):
    async def press_keys(dialogue, text):
        return Turn(["Press 1 to approve, or 2 to refuse."], control="gather_dtmf")

    d = Dialogue(languages=configure("en-IN"), llm=Conversation(FakeAnthropic()), flows={"approve": press_keys},
                 caller=Caller(person_id="p-dana", display_name="Dana Osei"), caller_phone="+919990000150")
    return agent.CallSession(ws, dialogue=d, sarvam_transport=FakeSarvam(["approve my pending items"]).transport())


async def test_the_stream_stops_only_after_vobiz_says_the_prompt_was_played(monkeypatch):
    monkeypatch.setattr(agent, "PLAYBACK_GRACE_S", 30.0)
    ws = FakeWS()
    s = _session_with_control(ws)
    await s.handle_message(NESTED_START)
    task = asyncio.create_task(s._process(b"\xff" * 1600))
    while not any(e["event"] == "checkpoint" and e["name"] == f"tts-{s._played}" for e in ws.sent[1:]) \
            or s._played < 2:
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.05)
    assert not any(e["event"] == "stop" for e in ws.sent)
    await s.handle_message(json.dumps({"event": "playedStream", "name": f"tts-{s._played}"}))
    await asyncio.wait_for(task, 5)
    assert ws.sent[-1] == {"event": "stop", "streamId": "stream-9"}
    assert s.dialogue.take_next_step() == "gather_dtmf"


async def test_without_an_acknowledgement_the_stream_still_stops_after_the_audio_and_a_grace(monkeypatch):
    monkeypatch.setattr(agent, "PLAYBACK_GRACE_S", 0.05)
    ws = FakeWS()
    s = _session_with_control(ws)
    await s.handle_message(NESTED_START)
    await asyncio.wait_for(s._process(b"\xff" * 1600), 5)
    assert ws.sent[-1] == {"event": "stop", "streamId": "stream-9"}


def test_the_answer_xml_hands_control_back_to_the_door_when_the_stream_stops():
    w = World()
    xml = w.answer(DANA_RAW).text
    assert xml.rstrip().endswith(f'<Redirect method="POST">{PUBLIC}/next</Redirect>\n</Response>')
    assert "<Hangup/>" not in xml


def test_next_serves_a_one_digit_gather_when_a_key_is_wanted_and_hangs_up_otherwise():
    w = World()
    w.answer(DANA_RAW)
    call = w.app.state.calls.get("call-1")
    call.dialogue = Dialogue(languages=configure("en-IN"), llm=Conversation(None))
    call.dialogue._turn(Turn([], control="gather_dtmf"))
    gather = w.client.post("/next", data={"CallUUID": "call-1"}, headers=signed("/next")).text
    assert (f'<Gather action="{PUBLIC}/dtmf" method="POST" inputType="dtmf" numDigits="1" '
            f'executionTimeout="15">') in gather
    assert f'<Redirect method="POST">{PUBLIC}/dtmf</Redirect>' in gather  # no input: the door still hears back
    again = w.client.post("/next", data={"CallUUID": "call-1"}, headers=signed("/next")).text
    assert "<Hangup/>" in again and "<Gather" not in again
    assert w.client.post("/next", data={"CallUUID": "call-1"}).status_code == 403


async def test_a_pressed_key_is_decided_by_the_engine_and_the_stream_resumes_with_the_outcome():
    w = World()
    w.engine.pending["p-dana"] = [__import__("tests.fake_engine", fromlist=["run_view"]).run_view(rows=[FIGMA])]
    r = w.answer(DANA_RAW)
    ws_path = w.ws_path(r.text)
    with w.client.websocket_connect(ws_path) as ws:
        ws.send_text(START)
        ws.receive_json()
    dialogue = w.app.state.calls.get("call-1").dialogue
    await dialogue.on_utterance("approve my pending items")
    assert (await dialogue.on_utterance("yes")).control == "gather_dtmf"

    assert w.client.post("/dtmf", data={"CallUUID": "call-1", "Digits": "1"}).status_code == 403
    assert not [q for q in w.engine.requests if q.url.path.endswith("/decisions")]

    resumed = w.client.post("/dtmf", data={"CallUUID": "call-1", "Digits": "1", "InputType": "dtmf"},
                            headers=signed("/dtmf"))
    [decision] = [q for q in w.engine.requests if q.url.path.endswith("/decisions")]
    assert json.loads(decision.content) | {} == {"action_id": "a-figma", "params_hash": HASH_A, "channel": "voice",
                                                 "actor_external_id": "+919990000150", "decision": "approved",
                                                 "reason": None}
    assert w.ws_path(resumed.text) == ws_path  # the same call's stream, resumed
    spoken = len(w.sarvam.tts)
    with w.client.websocket_connect(ws_path) as ws:
        ws.send_text(START)
        ws.receive_json()
    assert w.sarvam.spoken()[spoken].startswith(dialogue.line("decided_approved"))


@pytest.mark.parametrize("path", ["/next", "/dtmf"])
def test_callbacks_for_an_unknown_call_just_hang_up(path):
    w = World()
    r = w.client.post(path, data={"CallUUID": "no-such-call", "Digits": "1"}, headers=signed(path))
    assert r.status_code == 200 and re.search(r"<Hangup/>", r.text)

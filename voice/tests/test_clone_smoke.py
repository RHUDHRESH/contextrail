"""The Vobiz-Sarvam base still behaves as upstream documents it: health, the answer XML, the audio conversions and
the 800 ms VAD. Offline: no Sarvam, Vobiz, model or engine call is made.
"""

import audioop
import json
import math
import struct

import httpx
import pytest

import agent
import server
from engine_client import EngineClient
from languages import configure
from llm import Conversation


@pytest.fixture
def client():
    app = server.create_app(public_url="https://voice.test", vobiz_auth_token="",
                            engine=EngineClient("http://engine.test", ""), languages=configure("hi-IN"),
                            llm=Conversation(None))
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://voice.test")


async def test_health_reports_ok(client):
    r = await client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


async def test_answer_returns_a_bidirectional_mulaw_stream(client):
    r = await client.post("/answer", data={"CallUUID": "call-1", "From": "919990000150"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/xml")
    xml = r.text
    assert 'bidirectional="true"' in xml and 'keepCallAlive="true"' in xml
    assert 'contentType="audio/x-mulaw;rate=8000"' in xml
    assert "wss://voice.test/ws/" in xml


def _tone(ms: int, amplitude: int) -> bytes:
    samples = [int(amplitude * math.sin(2 * math.pi * 440 * n / 8000)) for n in range(8 * ms)]
    return audioop.lin2ulaw(struct.pack(f"<{len(samples)}h", *samples), 2)


def test_mulaw_wav_round_trip_keeps_8khz_mono():
    s = agent.CallSession(ws=None)
    mulaw = _tone(200, 8000)
    wav = s._mulaw_to_wav(mulaw)
    assert wav[:4] == b"RIFF"
    assert s._wav_to_mulaw(wav) == mulaw


class _WS:
    def __init__(self):
        self.sent = []

    async def send_text(self, data):
        self.sent.append(json.loads(data))


async def test_vad_hands_one_utterance_to_the_pipeline_after_800ms_of_silence(monkeypatch):
    s = agent.CallSession(_WS())
    got = []

    async def fake_process(audio):
        got.append(audio)

    monkeypatch.setattr(s, "_process", fake_process)
    speech, silence = _tone(20, 8000), _tone(20, 0)
    for _ in range(10):
        await s._handle_audio(speech)
    for _ in range(agent.SILENCE_FRAMES):
        await s._handle_audio(silence)
    await __import__("asyncio").sleep(0)
    assert len(got) == 1 and len(got[0]) == 160 * (10 + agent.SILENCE_FRAMES)

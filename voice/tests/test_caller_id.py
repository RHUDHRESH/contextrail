"""T200: URL-only Vobiz signatures do not prove caller ID; all callers get general policy questions only.

The signature is computed here independently from Vobiz's documented formula (vobiz.ai/docs/concepts/
validating-callbacks): base64(HMAC-SHA256(auth_token, baseURL + "." + nonce)) in X-Vobiz-Signature-V3.
"""

import base64
import hashlib
import hmac
import json
import logging
import re
import secrets

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from calls import normalize_phone
from dialogue import Dialogue
from engine_client import Caller, EngineClient
from languages import configure
from llm import Conversation
from server import create_app
from tests.fake_engine import TOKEN, FakeEngine
from tests.fake_sarvam import FakeSarvam
from tests.fakes import FakeAnthropic

PUBLIC = "https://cr.example.test/voice"
AUTH_TOKEN = "vobiz-test-auth-token"  # not a real credential
DANA_RAW, STRANGER_RAW = "919990000150", "919876500000"
START = json.dumps({"event": "start", "start": {"callId": "call-1", "streamId": "stream-1"}})


def signed(path: str, token: str = AUTH_TOKEN, nonce: str | None = None) -> dict:
    nonce = nonce or secrets.token_hex(12)
    mac = hmac.new(token.encode(), f"{PUBLIC}{path}.{nonce}".encode(), hashlib.sha256).digest()
    return {"X-Vobiz-Signature-V3": base64.b64encode(mac).decode(), "X-Vobiz-Signature-V3-Nonce": nonce}


class World:
    def __init__(self, *, auth_token=AUTH_TOKEN, transfer_number="", vobiz_auth_id="", vobiz_transport=None):
        self.engine, self.sarvam = FakeEngine(), FakeSarvam()
        self.app = create_app(public_url=PUBLIC, vobiz_auth_token=auth_token,
                              engine=EngineClient("http://engine.test", TOKEN, transport=self.engine.transport()),
                              languages=configure("en-IN"), llm=Conversation(FakeAnthropic()),
                              sarvam_transport=self.sarvam.transport(), transfer_number=transfer_number,
                              vobiz_auth_id=vobiz_auth_id, vobiz_transport=vobiz_transport)
        self.client = TestClient(self.app)

    def answer(self, caller: str, call_uuid: str = "call-1", headers: dict | None = None):
        return self.client.post("/answer", data={"CallUUID": call_uuid, "From": caller, "To": "918000000000"},
                                headers=signed("/answer") if headers is None else headers)

    def ws_path(self, xml: str) -> str:
        url = re.search(r"(wss://\S+)\s*</Stream>", xml).group(1)
        assert url.startswith("wss://cr.example.test/voice/ws/")
        return url.removeprefix("wss://cr.example.test/voice")

    def opening(self, caller: str) -> tuple[str, Dialogue]:
        r = self.answer(caller)
        assert r.status_code == 200, r.text
        with self.client.websocket_connect(self.ws_path(r.text)) as ws:
            ws.send_text(START)
            ws.receive_json()  # first playAudio frame: the opening has been synthesised
        call = self.app.state.calls.get("call-1")
        return self.sarvam.spoken()[0], call.dialogue


@pytest.mark.parametrize(("raw", "e164"), [
    ("919990000150", "+919990000150"), ("+919990000150", "+919990000150"), ("+91 99900-00150", "+919990000150"),
    ("9990000150", None), ("sip:someone@app.vobiz.ai", None), ("", None), (None, None)])
def test_caller_numbers_are_normalised_to_e164_or_not_trusted(raw, e164):
    assert normalize_phone(raw) == e164


def test_signed_from_field_cannot_claim_a_registered_caller():
    w = World()
    first, dialogue = w.opening(DANA_RAW)
    resolve = [json.loads(r.content) for r in w.engine.requests if r.url.path == "/v1/identities/resolve"]
    assert resolve == []
    assert dialogue.caller is None and dialogue.caller_phone is None
    assert first == dialogue.disclosed("unregistered")


def test_tampering_with_from_does_not_gain_the_registered_callers_identity():
    w = World()
    headers = signed("/answer")
    r = w.answer(DANA_RAW, headers=headers)
    assert r.status_code == 200
    assert w.app.state.calls.get("call-1").caller is None
    # A second call can also carry Dana's From field with a fresh valid URL signature; neither is trusted.
    assert w.answer(DANA_RAW, call_uuid="call-2", headers=signed("/answer")).status_code == 200
    assert w.app.state.calls.get("call-2").caller is None


def _live_call(request):
    assert request.method == "GET"
    assert request.url.path == "/api/v1/Account/MA-test/Call/call-1/"
    assert request.url.params["status"] == "live"
    assert request.headers["X-Auth-ID"] == "MA-test"
    return httpx.Response(200, json={"call_uuid": "call-1", "direction": "inbound", "call_status": "in-progress",
                                    "from": DANA_RAW, "to": "918000000000"})


def test_authenticated_live_call_readback_allows_registered_caller():
    w = World(vobiz_auth_id="MA-test", vobiz_transport=httpx.MockTransport(_live_call))
    first, dialogue = w.opening(DANA_RAW)
    assert dialogue.caller == Caller(person_id="p-dana", display_name="Dana Osei")
    assert dialogue.caller_phone == "+919990000150"
    assert first == dialogue.disclosed("menu")


@pytest.mark.parametrize("change", ["from", "call_uuid", "direction", "to", "call_status"])
def test_provider_readback_mismatch_rejects_caller_identity(change):
    def altered(request):
        body = _live_call(request).json()
        body[change] = {"from": STRANGER_RAW, "call_uuid": "other", "direction": "outbound",
                        "to": "919876500000", "call_status": "completed"}[change]
        return httpx.Response(200, json=body)

    w = World(vobiz_auth_id="MA-test", vobiz_transport=httpx.MockTransport(altered))
    _, dialogue = w.opening(DANA_RAW)
    assert dialogue.caller is None and dialogue.caller_phone is None


def test_provider_lookup_error_rejects_caller_identity():
    w = World(vobiz_auth_id="MA-test", vobiz_transport=httpx.MockTransport(lambda request: httpx.Response(503)))
    _, dialogue = w.opening(DANA_RAW)
    assert dialogue.caller is None


def test_replayed_signature_is_rejected_even_when_the_form_body_changes():
    w = World()
    headers = signed("/answer", nonce="one-time-nonce")
    assert w.answer(STRANGER_RAW, headers=headers).status_code == 200
    assert w.answer(DANA_RAW, call_uuid="call-2", headers=headers).status_code == 403
    assert w.app.state.calls.get("call-2") is None


def test_an_unknown_caller_is_told_they_get_policy_questions_only():
    w = World()
    first, dialogue = w.opening(STRANGER_RAW)
    assert dialogue.caller is None and dialogue.caller_phone is None
    assert first == dialogue.disclosed("unregistered")


@pytest.mark.parametrize("headers", [{}, signed("/answer", token="someone-else"), signed("/hangup")])
def test_an_unsigned_or_forged_answer_callback_is_refused(headers):
    w = World()
    r = w.answer(DANA_RAW, headers=headers)
    assert r.status_code == 403 and w.app.state.calls.get("call-1") is None


def test_without_a_vobiz_token_no_caller_id_is_trusted():
    w = World(auth_token="")
    first, dialogue = w.opening(DANA_RAW)  # even Dana's number: nothing proves the callback came from Vobiz
    assert dialogue.caller is None and first == dialogue.disclosed("unregistered")
    assert not [r for r in w.engine.requests if r.url.path == "/v1/identities/resolve"]
    assert w.client.get("/health").json()["modes"]["vobiz_callbacks"] == "FIXTURE"


def test_an_unreachable_engine_leaves_the_caller_unknown():
    w = World()
    w.engine.fail_with = 503
    _, dialogue = w.opening(DANA_RAW)
    assert dialogue.caller is None


def test_a_media_socket_without_a_live_call_token_is_refused():
    w = World()
    with pytest.raises(WebSocketDisconnect) as refused, w.client.websocket_connect("/ws/not-a-token") as ws:
        ws.send_text(START)
    assert refused.value.code == 1008 and w.sarvam.tts == []


def test_the_caller_number_never_reaches_the_xml_or_the_logs(caplog):
    w = World()
    with caplog.at_level(logging.DEBUG):
        r = w.answer(DANA_RAW)
        with w.client.websocket_connect(w.ws_path(r.text)) as ws:
            ws.send_text(START)
            ws.receive_json()
    assert "9990000150" not in r.text and "call-1" not in w.ws_path(r.text)
    assert "9990000150" not in caplog.text


@pytest.mark.parametrize("said", ["give Anil the same access as Rahul", "what happened to my request",
                                  "approve my pending items"])
async def test_unknown_callers_cannot_request_ask_status_or_approve(said):
    d = Dialogue(languages=configure("en-IN"), llm=Conversation(FakeAnthropic(error=RuntimeError("unused"))))
    turn = await d.on_utterance(said)
    assert turn.say == [d.line("unregistered")]

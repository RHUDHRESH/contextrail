"""T196: the voice door reaches the engine only through its HTTP door (/v1), with the bearer ENGINE_TOKEN, and sends
exactly the shapes engine/contextrail/surfaces/rest.py accepts. It passes identities and params_hash through
untouched and never decides anything itself (D-005)."""

import uuid

import httpx
import pytest

from engine_client import EngineClient, EngineError
from tests.fake_engine import HASH_A, TOKEN, FakeEngine, row, run_view

ANIL, DANA, STRANGER = "+919990000142", "+919990000150", "+919876500000"


@pytest.fixture
def engine():
    return FakeEngine()


@pytest.fixture
def client(engine):
    return EngineClient("http://engine.test", TOKEN, transport=engine.transport())


async def test_start_run_posts_the_request_as_a_voice_door_with_the_bearer_token(client, engine):
    view = await client.start_run("Anil ko Rahul jaisa access do", actor=ANIL, source_ref="call-uuid-1")
    req = engine.requests[-1]
    assert (req.method, req.url.path) == ("POST", "/v1/runs")
    assert req.headers["authorization"] == f"Bearer {TOKEN}"
    assert engine.body() == {"request_text": "Anil ko Rahul jaisa access do", "channel": "voice",
                             "actor_external_id": ANIL, "source_ref": "call-uuid-1"}
    assert view.status == "awaiting_approval" and view.request_text == "Anil ko Rahul jaisa access do"


async def test_voice_request_returns_the_ticket_only_after_engine_verification(client, engine):
    result = await client.start_voice_request("same as Rahul", actor=ANIL, source_ref="call-7")
    assert engine.requests[-1].url.path == "/v1/voice/requests"
    assert engine.body() == {"request_text": "same as Rahul", "actor_external_id": ANIL,
                             "source_ref": "call-7"}
    assert result.run.status == "awaiting_approval"
    assert (result.ticket.status, result.ticket.ticket_id, result.ticket.mode) == ("verified", 4413, "FIXTURE")


async def test_get_status_reads_the_run_view(client, engine):
    started = await client.start_run("same as Rahul", actor=ANIL, source_ref="c1")
    again = await client.get_status(started.run_id)
    assert engine.requests[-1].url.path == f"/v1/runs/{started.run_id}" and again == started


async def test_decide_sends_the_exact_action_and_params_hash_and_returns_the_engine_outcome(client, engine):
    rid = uuid.uuid4()
    result = await client.decide(rid, "a-07", HASH_A, actor=DANA, decision="approved")
    req = engine.requests[-1]
    assert (req.method, req.url.path) == ("POST", f"/v1/runs/{rid}/decisions")
    assert engine.body() == {"action_id": "a-07", "params_hash": HASH_A, "channel": "voice",
                             "actor_external_id": DANA, "decision": "approved", "reason": None}
    assert result.outcome == "recorded" and result.decided_by == "p-dana"


async def test_a_rejected_decision_is_an_answer_not_an_error(client, engine):
    engine.decision = {"outcome": "rejected", "reason": "only Meera Iyer can decide this", "rule_id": None,
                       "decided_by": None, "decided_channel": None, "view": None}
    result = await client.decide(uuid.uuid4(), "a-07", HASH_A, actor=DANA, decision="refused")
    assert result.outcome == "rejected" and "Meera" in result.reason


async def test_questions_go_to_the_query_endpoint_and_unknown_callers_send_no_identity(client, engine):
    a = await client.answer_query("can contractors get production access?", actor=None)
    assert (engine.requests[-1].method, engine.requests[-1].url.path) == ("POST", "/v1/queries")
    assert engine.body() == {"question": "can contractors get production access?", "channel": "voice",
                             "actor_external_id": None}
    assert a.text == "Your request is awaiting approval." and a.citations == [12, 14]


async def test_caller_identity_is_resolved_by_the_engine_and_the_number_stays_out_of_the_url(client, engine):
    person = await client.resolve_caller(DANA)
    req = engine.requests[-1]
    assert (req.method, req.url.path) == ("POST", "/v1/identities/resolve")
    assert "9990000150" not in str(req.url)  # phone numbers are PII: never in URLs or access logs (§16)
    assert engine.body() == {"channel": "voice", "external_id": DANA}
    assert (person.person_id, person.display_name) == ("p-dana", "Dana Osei")
    assert await client.resolve_caller(STRANGER) is None


async def test_pending_approvals_come_back_as_run_views(client, engine):
    engine.pending["p-dana"] = [run_view(rows=[row("a-07", label="Figma seat")])]
    runs = await client.pending_approvals(actor=DANA)
    assert engine.body() == {"channel": "voice", "actor_external_id": DANA}
    assert [r.label for v in runs for r in v.rows] == ["Figma seat"]
    assert runs[0].rows[0].params_hash == HASH_A


@pytest.mark.parametrize("status", [401, 404, 422, 500, 503])
async def test_engine_failures_raise_one_error_type(engine, status):
    engine.fail_with = status
    client = EngineClient("http://engine.test", TOKEN, transport=engine.transport())
    with pytest.raises(EngineError) as e:
        await client.get_status(uuid.uuid4())
    assert e.value.status == status


async def test_an_unreachable_engine_is_an_engine_error():
    def down(request):
        raise httpx.ConnectError("connection refused", request=request)

    client = EngineClient("http://engine.test", TOKEN, transport=httpx.MockTransport(down))
    with pytest.raises(EngineError) as e:
        await client.start_run("x", actor=ANIL, source_ref="c")
    assert e.value.status is None


@pytest.mark.parametrize("token", ["", "change-me"])
async def test_an_unset_or_placeholder_token_sends_nothing(engine, token):
    client = EngineClient("http://engine.test", token, transport=engine.transport())
    assert not client.configured
    with pytest.raises(EngineError):
        await client.answer_query("hello", actor=None)
    assert engine.requests == []

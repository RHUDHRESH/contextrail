"""The voice HTTP contract resolves callers and reads the same run facts as every other door."""

import asyncio

from contextrail.connectors.base import UnknownOutcome
from contextrail.surfaces.freshservice import request_fs_approval, ticket_for_run

ANIL = "+919990000142"
DANA = "+919990000150"
UNKNOWN = "+919999999999"
REQUEST = "Give Anil the same access as Rahul Mehta"


async def test_voice_caller_resolution_returns_only_the_identity_needed_by_the_phone(api):
    client, _ = api
    response = await client.post("/v1/identities/resolve", json={"channel": "voice", "external_id": ANIL})
    assert response.status_code == 200
    assert response.json() == {"person_id": "p-anil", "display_name": "Anil Kumar"}
    missing = await client.post("/v1/identities/resolve", json={"channel": "voice", "external_id": UNKNOWN})
    assert missing.status_code == 404


async def test_voice_query_reads_the_verified_run_and_unknown_caller_gets_no_private_facts(api):
    client, _ = api
    started = await client.post("/v1/runs", json={"request_text": REQUEST, "channel": "voice",
                                                 "actor_external_id": ANIL, "source_ref": "call-voice-rest-1"})
    assert started.status_code == 201
    answer = await client.post("/v1/queries", json={"question": "What's the update on my request?",
                                                   "channel": "voice", "actor_external_id": ANIL})
    assert answer.status_code == 200
    assert answer.json()["run_id"] == started.json()["run_id"]
    assert "15 done and verified" in answer.json()["text"]
    assert answer.json()["citations"]
    unknown = await client.post("/v1/queries", json={"question": "What's the update on my request?",
                                                    "channel": "voice", "actor_external_id": UNKNOWN})
    assert unknown.status_code == 200
    assert unknown.json()["run_id"] is None
    assert REQUEST not in unknown.json()["text"]


async def test_pending_approvals_are_limited_to_the_resolved_caller(api):
    client, _ = api
    started = await client.post("/v1/runs", json={"request_text": REQUEST, "channel": "voice",
                                                 "actor_external_id": ANIL, "source_ref": "call-voice-rest-2"})
    assert started.status_code == 201
    dana = await client.post("/v1/approvals/pending", json={"channel": "voice", "actor_external_id": DANA})
    assert dana.status_code == 200
    assert [r["run_id"] for r in dana.json()["runs"]] == [started.json()["run_id"]]
    assert any(r["approver_id"] == "p-dana" and r["state"] == "awaiting"
               for r in dana.json()["runs"][0]["rows"])
    anil = await client.post("/v1/approvals/pending", json={"channel": "voice", "actor_external_id": ANIL})
    unknown = await client.post("/v1/approvals/pending", json={"channel": "voice", "actor_external_id": UNKNOWN})
    assert anil.json() == unknown.json() == {"runs": []}


async def test_voice_request_creates_one_verified_fixture_ticket_and_native_approval(api):
    client, platform = api
    body = {"request_text": REQUEST, "actor_external_id": ANIL, "source_ref": "call-ticket-1"}
    first = await client.post("/v1/voice/requests", json=body)
    assert first.status_code == 200, first.text
    data = first.json()
    assert data["run"]["source"] == "voice"
    assert data["ticket"]["status"] == "verified" and data["ticket"]["mode"] == "FIXTURE"
    tid = data["ticket"]["ticket_id"]
    fs = platform.registry.get("freshservice")
    ticket = await fs.get_ticket(tid)
    items = await fs.get_requested_items(tid)
    assert ticket.data["id"] == tid
    assert items.data[0]["custom_fields"]["request_text"] == REQUEST
    again = await client.post("/v1/voice/requests", json=body)
    assert again.status_code == 200 and again.json() == data
    async with platform.db.connection() as c:
        n = (await (await c.execute("select count(*) as n from runs where source = 'voice' "
                                    "and source_ref = %s", (body["source_ref"],))).fetchone())["n"]
        run = await (await c.execute("select * from runs where id = %s", (data["run"]["run_id"],))).fetchone()
        assert await ticket_for_run(c, run, "FIXTURE") == tid
        assert await ticket_for_run(c, run, "LIVE") is None
    assert n == 1
    held = next(row for row in data["run"]["rows"] if row["state"] == "awaiting")
    approval = await request_fs_approval(platform, data["run"]["run_id"], held["action_id"])
    assert approval["status"] == "requested" and approval["ticket_id"] == tid


async def test_voice_request_rejects_unknown_caller_and_reused_call_for_different_request(api):
    client, _ = api
    body = {"request_text": REQUEST, "actor_external_id": ANIL, "source_ref": "call-ticket-2"}
    assert (await client.post("/v1/voice/requests", json={**body,
                                                          "actor_external_id": UNKNOWN})).status_code == 403
    assert (await client.post("/v1/voice/requests", json=body)).status_code == 200
    changed = await client.post("/v1/voice/requests", json={**body, "request_text": "another request"})
    assert changed.status_code == 409


async def test_uncertain_ticket_write_is_never_retried_for_the_same_call(api, monkeypatch):
    client, platform = api
    fs = platform.registry.get("freshservice")
    attempts = 0

    async def uncertain(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        raise UnknownOutcome("outcome unknown")

    monkeypatch.setattr(fs, "place_access_request", uncertain)
    body = {"request_text": REQUEST, "actor_external_id": ANIL, "source_ref": "call-ticket-uncertain"}
    first = await client.post("/v1/voice/requests", json=body)
    again = await client.post("/v1/voice/requests", json=body)
    assert first.status_code == again.status_code == 200
    assert first.json()["ticket"]["status"] == again.json()["ticket"]["status"] == "unknown"
    assert first.json()["ticket"]["ticket_id"] is None
    assert attempts == 1


async def test_concurrent_same_call_creates_at_most_one_ticket(api):
    client, _ = api
    body = {"request_text": REQUEST, "actor_external_id": ANIL, "source_ref": "call-ticket-concurrent"}
    responses = await asyncio.gather(*(client.post("/v1/voice/requests", json=body) for _ in range(3)))
    assert all(r.status_code == 200 for r in responses)
    assert len({r.json()["run"]["run_id"] for r in responses}) == 1
    assert len({r.json()["ticket"]["ticket_id"] for r in responses if r.json()["ticket"]["ticket_id"]}) == 1

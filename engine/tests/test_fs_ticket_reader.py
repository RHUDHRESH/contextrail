"""Freshservice ticket intake crosses the real connector, signed webhook, worker and shared Door."""

import json
import time

import httpx
import pytest

from contextrail.app_state import build_platform
from contextrail.connectors.base import TransientError
from contextrail.connectors.freshservice import FreshserviceConnector, FsRead
from contextrail.connectors.freshservice_ticket import FreshserviceTicketReader
from contextrail.connectors.state import FixtureState
from contextrail.jobs import Worker, load_handlers
from contextrail.knowledge.okf import load_bundle
from contextrail.main import create_app
from contextrail.settings import Settings
from contextrail.surfaces.webhooks import sign

SECRET = "test-webhook-secret-not-real"
REQUEST = "Give Anil the same access as Rahul Mehta"
EMAIL = "anil.kumar@northbeam.example"


async def test_reader_prefers_catalog_request_text_and_verified_requester_email(tmp_path):
    state = FixtureState("freshservice", directory=tmp_path)
    state.reset()
    fs = FreshserviceConnector(state=state)
    try:
        placed = await fs.place_access_request(EMAIL, REQUEST)
        tid = str(placed.data["id"])
        request = await FreshserviceTicketReader(fs).ticket_request(tid)
    finally:
        await fs.aclose()
    assert request.ticket_id == tid and request.text == REQUEST and request.requester_external_id == EMAIL


async def test_live_reader_never_processes_a_fixture_fallback_ticket():
    class FakeLive:
        mode = "LIVE"

        async def get_ticket(self, ticket_id):
            return FsRead(data={"id": int(ticket_id), "description_text": REQUEST}, mode="FIXTURE")

    with pytest.raises(TransientError, match="not read from the live tenant"):
        await FreshserviceTicketReader(FakeLive()).ticket_request("4412")


async def test_signed_ticket_webhook_worker_status_and_knowledge_query(rail):
    runner, deps = rail
    deps.knowledge = load_bundle()
    settings = Settings(_env_file=None, engine_token="test-engine-token", fs_webhook_secret=SECRET)
    platform = build_platform(settings, runner=runner)
    app = create_app(settings, platform=platform)
    fs = platform.registry.get("freshservice")
    placed = await fs.place_access_request(EMAIL, REQUEST)
    tid = str(placed.data["id"])
    body = json.dumps({"ticket_id": int(tid)}).encode()
    timestamp = int(time.time())
    headers = {"Authorization": "Bearer test-engine-token", "X-ContextRail-Timestamp": str(timestamp),
               "X-ContextRail-Signature": sign(SECRET, body, timestamp), "Content-Type": "application/json"}
    async with platform.serving(worker=False):  # noqa: SIM117 -- the outer context indexes knowledge before HTTP
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://engine.test",
                                     headers={"Authorization": "Bearer test-engine-token"}) as client:
            accepted = await client.post("/v1/webhooks/freshservice", content=body, headers=headers)
            assert accepted.status_code == 202, accepted.text
            assert platform.tickets is not None and platform.tickets.mode == "FIXTURE"
            load_handlers()
            outcome = await Worker(platform.db, platform).run_once()
            assert outcome is not None and (outcome.kind, outcome.outcome) == ("rail.run", "done")
            async with platform.db.connection() as conn:
                run = await (await conn.execute("select id, requested_by from runs where source = 'freshservice' "
                                                "and source_ref = %s", (tid,))).fetchone()
            assert run is not None and run["requested_by"] == "p-anil"
            status = await client.get(f"/v1/runs/{run['id']}")
            assert status.status_code == 200 and status.json()["counts"]["verified"] == 15
            own = await client.post("/v1/queries", json={"question": "What's the update on my request?",
                                                       "channel": "freshservice", "actor_external_id": EMAIL})
            assert own.status_code == 200 and own.json()["run_id"] == str(run["id"])
            policy = await client.post("/v1/queries", json={"question": "Can contractors get production credentials?",
                                                          "channel": "freshservice", "actor_external_id": EMAIL})
            assert policy.status_code == 200
            assert "Contractors must never receive production credentials" in policy.json()["text"]
            assert any(c.startswith("okf:") for c in policy.json()["sources"])

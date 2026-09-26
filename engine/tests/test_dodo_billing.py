"""Dodo Payments in test mode (T206): honest mode, one usage event per completed run, the pilot checkout link.

The LIVE connector runs the official `dodopayments` SDK against an in-memory Dodo (fake_dodo.py) through
httpx.MockTransport: real SDK, real request shapes, no network.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fake_dodo import FakeDodo

from contextrail import billing, repo
from contextrail.connectors.base import ConnectorError, TransientError, UnknownOutcome
from contextrail.connectors.dodo import DodoTestMode, FixtureDodo, build_dodo
from contextrail.connectors.state import FixtureState
from contextrail.models import CaseFile, RunStatus, Subject
from contextrail.settings import Settings

KEY = "test-mode-placeholder-key"   # obviously fake; tests never see a real key
NOW = datetime(2026, 9, 26, 10, 0, tzinfo=UTC)


@pytest.fixture
def fake():
    return FakeDodo()


@pytest.fixture
def live(fake):
    return DodoTestMode(KEY, http_client=fake.client(), pilot_customer_id="cus_pilot", pilot_product_id="pdt_run")


@pytest.fixture
def fixture_dodo(tmp_path):
    return FixtureDodo(FixtureState("dodo_payments", directory=tmp_path))


def _payload(run_id=None, status="partial"):
    return {"run_id": str(run_id or uuid4()), "status": status, "intent": "access.same_as_peer",
            "action_count": 18, "allow": 15, "hold": 2, "refuse": 1, "verified": 17, "failed": 0,
            "finalized_at": "2026-09-26T09:59:00+00:00"}


# --- mode: FIXTURE without a key, LIVE only with one, and then always test mode ----------------------------------

def test_no_key_means_fixture():
    d = build_dodo(Settings(_env_file=None))
    assert isinstance(d, FixtureDodo) and d.mode == "FIXTURE" and d.label == "FIXTURE"


def test_no_settings_means_fixture_even_if_the_environment_has_a_key(monkeypatch):
    monkeypatch.setenv("DODO_API_KEY", KEY)
    monkeypatch.setenv("DODO_PAYMENTS_API_KEY", KEY)
    assert build_dodo(None).mode == "FIXTURE"   # tests and tools never reach Dodo by accident


def test_a_key_means_live_and_the_label_says_test_mode():
    d = build_dodo(Settings(_env_file=None, dodo_api_key=KEY, dodo_customer_id="cus_pilot",
                            dodo_product_id="pdt_run"))
    assert isinstance(d, DodoTestMode)
    assert (d.mode, d.environment) == ("LIVE", "test_mode")
    assert d.label == "LIVE · test mode"
    assert str(d.client.base_url).rstrip("/") == "https://test.dodopayments.com"
    assert (d.pilot_customer_id, d.pilot_product_id) == ("cus_pilot", "pdt_run")


def test_the_live_base_url_cannot_be_injected_through_the_environment(monkeypatch):
    monkeypatch.setenv("DODO_PAYMENTS_BASE_URL", "https://live.dodopayments.com")
    assert str(DodoTestMode(KEY).client.base_url).rstrip("/") == "https://test.dodopayments.com"


def test_sdk_retries_are_off_so_no_write_is_ever_blind_retried():
    assert DodoTestMode(KEY).client.max_retries == 0


def test_the_key_is_sent_as_a_bearer_token_and_never_rendered(live):
    assert KEY not in repr(live)


@pytest.mark.parametrize(("fault", "error"), [(503, TransientError), (429, TransientError),
                                              ("timeout", UnknownOutcome), (401, ConnectorError)])
async def test_dodo_failures_map_onto_the_connector_contract(live, fake, fault, error):
    fake.fail_next["POST /events/ingest"] = fault
    with pytest.raises(error) as info:
        await live.ingest_usage([billing.usage_event(_payload(), customer_id="cus_pilot", now=NOW)])
    assert type(info.value) is error      # a 401 is permanent, never "transient"
    assert len(fake.requests) == 1        # the SDK did not retry on its own


# --- usage events -----------------------------------------------------------------------------------------------

async def test_usage_event_is_sent_once_per_run_and_read_back(live, fake):
    p = _payload()
    out = await billing.send_usage_event(live, p, now=NOW)
    (body,) = fake.bodies("POST", "/events/ingest")
    (ev,) = body["events"]
    assert ev["event_id"] == p["run_id"]                     # idempotency: run_id (CLAUDE.md §14)
    assert ev["event_name"] == "contextrail.governed_run"
    assert ev["customer_id"] == "cus_pilot"
    assert ev["metadata"]["action_count"] == 18 and ev["metadata"]["status"] == "partial"
    assert all(isinstance(v, (str, int, float, bool)) for v in ev["metadata"].values())
    assert fake.requests[0].headers["authorization"] == f"Bearer {KEY}"
    assert (out.event_id, out.ingested, out.verified, out.mode, out.environment) == (
        p["run_id"], 1, True, "LIVE", "test_mode")


async def test_resending_the_same_run_is_ignored_by_dodo(live, fake):
    p = _payload()
    await billing.send_usage_event(live, p, now=NOW)
    again = await billing.send_usage_event(live, p, now=NOW)
    assert (again.ingested, again.replayed, again.verified) == (0, True, True)
    assert len(fake.events) == 1


async def test_usage_not_readable_after_ingest_is_not_verified(live, fake):
    fake.fail_next["GET /events/"] = 404
    out = await billing.send_usage_event(live, _payload(), now=NOW)
    assert out.ingested == 1 and out.verified is False       # a 200 is not done (P3)


async def test_live_usage_without_a_customer_is_a_permanent_error(fake):
    d = DodoTestMode(KEY, http_client=fake.client())
    with pytest.raises(ConnectorError, match="DODO_CUSTOMER_ID"):
        await billing.send_usage_event(d, _payload(), now=NOW)
    assert fake.requests == []


async def test_fixture_usage_is_idempotent_and_labelled(fixture_dodo):
    p = _payload()
    first = await billing.send_usage_event(fixture_dodo, p, now=NOW)
    second = await billing.send_usage_event(fixture_dodo, p, now=NOW)
    assert (first.ingested, first.verified, first.mode) == (1, True, "FIXTURE")
    assert (second.ingested, second.replayed) == (0, True)
    assert list(fixture_dodo.state.load()["events"]) == [p["run_id"]]


async def test_fixture_rejects_a_batch_with_duplicate_event_ids_like_dodo(fixture_dodo):
    ev = billing.usage_event(_payload(), customer_id="cus_x", now=NOW)
    with pytest.raises(ConnectorError, match="duplicate"):
        await fixture_dodo.ingest_usage([ev, ev])


# --- one usage job per completed run --------------------------------------------------------------------------

def _case(run_id):
    subject = Subject(source="hris", source_id="E-1042", display_name="Anil Kumar", employment_type="employee")
    return CaseFile(run_id=run_id, request_text="x", intent="access.same_as_peer", subject=subject)


async def _usage_jobs(db):
    async with db.connection() as c:
        return await (await c.execute("select payload from jobs where kind = 'dodo.usage'")).fetchall()


@pytest.mark.parametrize("status", [RunStatus.AWAITING_APPROVAL, RunStatus.NEEDS_INPUT, RunStatus.FAILED])
async def test_unfinished_runs_are_not_billed(rail, status):
    runner, deps = rail
    rid = await runner.start(source="slack", request_text="x")
    async with deps.db.transaction() as c:
        assert await billing.request_usage_event(c, _case(rid), status) is None
    assert await _usage_jobs(deps.db) == []


async def test_a_completed_run_enqueues_exactly_one_usage_job(rail):
    runner, deps = rail
    rid = await runner.start(source="slack", request_text="x")
    async with deps.db.transaction() as c:
        assert await billing.request_usage_event(c, _case(rid), RunStatus.DONE) is not None
        assert await billing.request_usage_event(c, _case(rid), RunStatus.DONE) is None   # deduped
    (job,) = await _usage_jobs(deps.db)
    assert job["payload"]["run_id"] == str(rid) and job["payload"]["status"] == "done"


async def test_the_rail_bills_a_run_when_it_completes_not_while_it_waits(rail):
    runner, deps = rail
    rid = await runner.start(source="slack", request_text="Give Anil the same access as Rahul Mehta",
                             requested_by="p-anil")
    assert await runner.run(rid) is RunStatus.AWAITING_APPROVAL
    assert await _usage_jobs(deps.db) == []
    async with deps.db.transaction() as c:
        for a in await repo.list_actions(c, rid):
            if a["state"] == "awaiting":
                await repo.record_approval(c, rid, a["id"], params_hash=a["params_hash"], approver=a["approver"],
                                           decision="approved", channel="slack")
    assert await runner.resume(rid) is RunStatus.PARTIAL
    (job,) = await _usage_jobs(deps.db)
    assert job["payload"]["status"] == "partial" and job["payload"]["action_count"] == 18


# --- the pilot checkout link ------------------------------------------------------------------------------------

async def test_pilot_checkout_link_in_test_mode(live, fake):
    link = await billing.pilot_checkout_link(live, return_url="https://contextrail.example.com/thanks",
                                             customer_email="pilot@northbeam.example", customer_name="Northbeam")
    (body,) = fake.bodies("POST", "/checkouts")
    assert body["product_cart"] == [{"product_id": "pdt_run", "quantity": 1}]
    assert body["customer"] == {"email": "pilot@northbeam.example", "name": "Northbeam"}
    assert body["return_url"] == "https://contextrail.example.com/thanks"
    assert link.url.startswith("https://test.checkout.dodopayments.com/")
    assert (link.mode, link.environment) == ("LIVE", "test_mode")


async def test_fixture_checkout_link_cannot_be_mistaken_for_a_real_one(fixture_dodo):
    link = await billing.pilot_checkout_link(fixture_dodo, return_url="https://contextrail.example.com/thanks")
    assert link.url.startswith("fixture://dodo/checkouts/") and link.mode == "FIXTURE"


async def test_checkout_without_a_product_is_a_permanent_error(fake):
    d = DodoTestMode(KEY, http_client=fake.client(), pilot_customer_id="cus_pilot")
    with pytest.raises(ConnectorError, match="DODO_PRODUCT_ID"):
        await billing.pilot_checkout_link(d, return_url="https://contextrail.example.com/thanks")

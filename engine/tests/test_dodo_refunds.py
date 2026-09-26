"""Refunds through Dodo (T207): one refund per idempotency key, and `verified` only from a read-back (P3).

Dodo takes no idempotency key on POST /refunds, so the connector stamps ours into the refund's metadata and looks
for it before it creates anything. Verify reads the refund back and compares status and amount.
"""

from uuid import uuid4

import pytest
from fake_dodo import FakeDodo

from contextrail.canonical import idempotency_key
from contextrail.connectors.base import ConnectorError, UnknownOutcome
from contextrail.connectors.dodo import DodoTestMode, FixtureDodo
from contextrail.connectors.state import FixtureState
from contextrail.models import Action

KEY = "test-mode-placeholder-key"
RUN = str(uuid4())


def refund(amount=45000, payment="pay_1", item="pdt_platform", action_id="C01", **extra):
    target = {"system": "dodo", "run_id": RUN, "account_id": "ACC-2041", "customer_id": "cus_acme",
              "payment_id": payment, "item_id": item, "amount_minor": amount, "amount_usd": amount / 100,
              "currency": "USD", "credit_type": "outage", "quarter": "2026-Q3",
              "prior_outage_credits_in_quarter": 0, "promise_ref": "FD-7001", "incident_id": "INC-4412",
              "label": f"Refund ${amount / 100:,.2f}", **extra}
    return Action.create(action_id, "refund", target)


def key(a):
    return idempotency_key(a.target["run_id"], a.id, a.params_hash)


@pytest.fixture
def fake():
    f = FakeDodo()
    f.add_payment("pay_1", customer_id="cus_acme", total=480000)
    return f


@pytest.fixture
def live(fake):
    async def no_sleep(_):
        return None
    return DodoTestMode(KEY, http_client=fake.client(), sleep=no_sleep)


@pytest.fixture
def fx(tmp_path):
    return FixtureDodo(FixtureState("dodo_payments", directory=tmp_path))


# --- LIVE (test mode), through the real SDK ---------------------------------------------------------------------

async def test_partial_refund_carries_our_key_and_is_verified_by_read_back(live, fake):
    a = refund()
    out = await live.write(a, key(a))
    (body,) = fake.bodies("POST", "/refunds")
    assert body["payment_id"] == "pay_1"
    assert body["items"] == [{"item_id": "pdt_platform", "amount": 45000}]
    assert body["metadata"]["contextrail_idempotency_key"] == key(a)
    assert body["metadata"]["promise_ref"] == "FD-7001" and body["metadata"]["credit_type"] == "outage"
    assert (out.ok, out.replayed, out.mode, out.ref["refund_id"]) == (True, False, "LIVE", "ref_test_1")
    ok, seen = await live.verify(a)
    assert ok and seen == {"refund_id": "ref_test_1", "status": "succeeded", "amount": 45000, "currency": "USD",
                           "payment_id": "pay_1"}


async def test_full_amount_is_a_full_refund_without_items(live, fake):
    a = refund(amount=480000)
    await live.write(a, key(a))
    (body,) = fake.bodies("POST", "/refunds")
    assert "items" not in body


async def test_the_same_key_never_refunds_twice(live, fake):
    a = refund()
    await live.write(a, key(a))
    again = await live.write(a, key(a))
    assert again.replayed and again.ref["refund_id"] == "ref_test_1"
    assert len(fake.bodies("POST", "/refunds")) == 1 and len(fake.refunds) == 1


async def test_a_timed_out_refund_that_landed_is_found_not_repeated(live, fake):
    a = refund()
    fake.fail_next["POST /refunds"] = "timeout_after"  # Dodo applied it, then the connection dropped
    with pytest.raises(UnknownOutcome):
        await live.write(a, key(a))
    assert (await live.verify(a))[0] is True           # the rail reconciles by reading back (§8 Execute)
    again = await live.write(a, key(a))
    assert again.replayed and len(fake.refunds) == 1


async def test_a_timed_out_refund_that_did_not_land_is_absent_then_written_once(live, fake):
    a = refund()
    fake.fail_next["POST /refunds"] = "timeout"        # the request never reached Dodo
    with pytest.raises(UnknownOutcome):
        await live.write(a, key(a))
    assert await live.verify(a) == (False, {"refund_id": None, "status": "absent", "payment_id": "pay_1"})
    await live.write(a, key(a))                        # same key: safe to retry once reconciled as absent
    assert (await live.verify(a))[0] is True and len(fake.refunds) == 1


async def test_pending_is_not_verified_after_the_read_back_window(live, fake):
    fake.refund_status = "pending"
    a = refund()
    await live.write(a, key(a))
    ok, seen = await live.verify(a)
    assert not ok and seen["status"] == "pending"
    reads = [r for r in fake.requests if r.method == "GET" and r.url.path == "/refunds/ref_test_1"]
    assert len(reads) >= 3                             # it read back more than once before saying no


async def test_a_refund_for_a_different_amount_is_not_verified(live, fake):
    a = refund()
    await live.write(a, key(a))
    fake.refunds["ref_test_1"]["amount"] = 4500
    ok, seen = await live.verify(a)
    assert not ok and seen["amount"] == 4500


async def test_unknown_payment_is_a_permanent_error(live):
    a = refund(payment="pay_missing")
    with pytest.raises(ConnectorError) as info:
        await live.write(a, key(a))
    assert type(info.value) is ConnectorError


async def test_customer_payments_include_refunds_with_metadata(live, fake):
    a = refund()
    await live.write(a, key(a))
    fake.add_payment("pay_2", customer_id="cus_other", total=1000)
    pays = await live.customer_payments("cus_acme")
    assert [p["payment_id"] for p in pays] == ["pay_1"]
    (r,) = pays[0]["refunds"]
    assert r["metadata"]["promise_ref"] == "FD-7001" and r["amount"] == 45000
    assert pays[0]["product_cart"] == [{"product_id": "pdt_platform", "quantity": 1}]


# --- FIXTURE ------------------------------------------------------------------------------------------------------

def fx_refund(**kw):
    return refund(payment="pay_fx_acme_0901", item="pdt_fx_platform", customer_id="cus_fx_acme", **kw)


async def test_fixture_refund_is_written_once_and_read_back(fx):
    a = fx_refund()
    first = await fx.write(a, key(a))
    second = await fx.write(a, key(a))
    assert (first.mode, first.replayed, second.replayed) == ("FIXTURE", False, True)
    ok, seen = await fx.verify(a)
    assert ok and seen["status"] == "succeeded" and seen["amount"] == 45000
    mine = [r for r in fx.state.load()["refunds"].values()
            if r["metadata"].get("contextrail_idempotency_key") == key(a)]
    assert len(mine) == 1


async def test_fixture_ack_without_apply_is_caught_by_verify(fx):
    a = fx_refund()
    await fx.state.inject_fault("pay_fx_acme_0901", "ack_without_apply")
    assert (await fx.write(a, key(a))).ok
    ok, seen = await fx.verify(a)
    assert not ok and seen["status"] == "absent"


async def test_fixture_refuses_more_than_the_payment_has_left(fx):
    a = fx_refund(amount=10_000_000)
    with pytest.raises(ConnectorError, match="exceeds"):
        await fx.write(a, key(a))


async def test_fixture_refuses_a_payment_that_was_never_paid(fx):
    a = refund(payment="pay_fx_dunmore_0901", item="pdt_fx_platform", customer_id="cus_fx_dunmore")
    with pytest.raises(ConnectorError, match="not succeeded"):
        await fx.write(a, key(a))


async def test_fixture_customer_payments_carry_prior_refunds(fx):
    pays = {p["payment_id"]: p for p in await fx.customer_payments("cus_fx_cedar")}
    prior = pays["pay_fx_cedar_0701"]["refunds"]
    assert [(r["refund_id"], r["metadata"]["credit_type"], r["metadata"]["quarter"]) for r in prior] == [
        ("ref_fx_cedar_0715", "outage", "2026-Q3")]

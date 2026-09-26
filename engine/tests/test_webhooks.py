"""POST /v1/webhooks/freshservice (T132 signature, T133 dedupe + 202 + job; CLAUDE.md §13.2, §16).

Signature scheme (see contextrail/surfaces/webhooks.py):
  X-ContextRail-Timestamp: <unix seconds>
  X-ContextRail-Signature: sha256=<hex HMAC-SHA256(FS_WEBHOOK_SECRET, "<timestamp>.<raw body>")>
"""

import asyncio
import hashlib
import hmac
import json
import time

import httpx
import pytest

from contextrail.db import Database
from contextrail.main import create_app
from contextrail.settings import Settings
from contextrail.surfaces import webhooks
from contextrail.surfaces.webhooks import SignatureError, sign, verify_signature

SECRET = "test-webhook-secret-not-real"
URL = "/v1/webhooks/freshservice"


def app(secret: str = SECRET):
    return create_app(Settings(_env_file=None, fs_webhook_secret=secret))


@pytest.fixture
async def db(migrated_db):
    d = Database(migrated_db, max_size=4)
    await d.open()
    yield d
    await d.close()


def wired(db: Database, secret: str = SECRET):
    a = app(secret)
    a.state.db = db  # the lead's app wiring opens one Database and puts it here
    return a


async def rows(db: Database, sql: str) -> list[dict]:
    async with db.connection() as c:
        return await (await c.execute(sql)).fetchall()


def signed(body: bytes, *, ts: int | None = None, secret: str = SECRET) -> dict:
    ts = int(time.time()) if ts is None else ts
    return {"X-ContextRail-Timestamp": str(ts), "X-ContextRail-Signature": sign(secret, body, ts),
            "Content-Type": "application/json"}


async def post(application, body: bytes, headers: dict) -> httpx.Response:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://test") as c:
        return await c.post(URL, content=body, headers=headers)


BODY = json.dumps({"ticket_id": 4412}).encode()


# --- the scheme, as a pure function -----------------------------------------------------------------------------

def test_sign_is_hmac_sha256_over_timestamp_dot_body():
    expected = hmac.new(SECRET.encode(), b"1727340000." + BODY, hashlib.sha256).hexdigest()
    assert sign(SECRET, BODY, 1727340000) == f"sha256={expected}"


def test_a_good_signature_inside_the_window_verifies():
    verify_signature(SECRET, BODY, sign(SECRET, BODY, 1000), "1000", now=1000 + 299)
    verify_signature(SECRET, BODY, sign(SECRET, BODY, 1000).upper().replace("SHA256=", "sha256="), "1000", now=1000)


@pytest.mark.parametrize(("signature", "timestamp", "now", "reason"), [
    (None, "1000", 1000, "missing"),
    (sign(SECRET, BODY, 1000), None, 1000, "missing"),
    ("sha256=" + "0" * 64, "1000", 1000, "does not match"),
    (sign("another-secret", BODY, 1000), "1000", 1000, "does not match"),
    (sign(SECRET, BODY + b" ", 1000), "1000", 1000, "does not match"),     # body changed after signing
    (sign(SECRET, BODY, 1001), "1000", 1000, "does not match"),            # timestamp changed after signing
    (sign(SECRET, BODY, 1000), "1000", 1000 + 301, "outside"),             # replayed too late
    (sign(SECRET, BODY, 1000), "1000", 1000 - 301, "outside"),             # from the future
    ("md5=abc", "1000", 1000, "format"),
    (sign(SECRET, BODY, 1000), "10e3", 1000, "timestamp"),
])
def test_bad_signatures_are_refused_with_a_reason(signature, timestamp, now, reason):
    with pytest.raises(SignatureError, match=reason):
        verify_signature(SECRET, BODY, signature, timestamp, now=now)


def test_the_comparison_is_constant_time(monkeypatch):
    calls = []
    real = hmac.compare_digest
    monkeypatch.setattr(webhooks.hmac, "compare_digest", lambda a, b: calls.append(1) or real(a, b))
    verify_signature(SECRET, BODY, sign(SECRET, BODY, 1000), "1000", now=1000)
    assert calls == [1]


# --- the endpoint -----------------------------------------------------------------------------------------------

async def test_a_signed_delivery_is_accepted_with_202(db):
    r = await post(wired(db), BODY, signed(BODY))
    assert r.status_code == 202 and r.json()["accepted"] is True and r.json()["ticket_id"] == 4412


async def test_an_unsigned_or_forged_delivery_is_401_problem_json():
    for headers in ({"Content-Type": "application/json"}, signed(BODY, secret="guessed-secret")):
        r = await post(app(), BODY, headers)
        assert r.status_code == 401 and r.headers["content-type"].startswith("application/problem+json")


async def test_a_stale_delivery_is_refused():
    r = await post(app(), BODY, signed(BODY, ts=int(time.time()) - 301))
    assert r.status_code == 401 and "outside" in r.json()["detail"]


async def test_without_a_configured_secret_every_delivery_is_refused():
    r = await post(app(secret=""), BODY, signed(BODY, secret=""))
    assert r.status_code == 503


@pytest.mark.parametrize("payload", [{}, {"ticket_id": 0}, {"ticket_id": "SR-4412"}, {"ticket_id": "4412; drop"},
                                     {"ticket_id": 4412.5}, {"ticket_id": True}])
async def test_a_signed_but_malformed_payload_is_422(payload):
    body = json.dumps(payload).encode()
    r = await post(app(), body, signed(body))
    assert r.status_code == 422


async def test_a_numeric_string_ticket_id_is_accepted(db):
    body = json.dumps({"ticket_id": "4412"}).encode()   # Workflow Automator placeholders may render as strings
    r = await post(wired(db), body, signed(body))
    assert r.status_code == 202 and r.json()["ticket_id"] == 4412


async def test_an_oversized_body_is_refused_before_anything_else():
    body = json.dumps({"ticket_id": 4412, "pad": "x" * 20_000}).encode()
    r = await post(app(), body, signed(body))
    assert r.status_code == 413


# --- T133: dedupe by ticket id, 202 at once, a job instead of an inline run -------------------------------------

async def test_the_first_delivery_enqueues_one_rail_run_job_and_starts_nothing_inline(db):
    r = await post(wired(db), BODY, signed(BODY))
    assert r.status_code == 202
    assert (r.json()["duplicate"], isinstance(r.json()["job_id"], int)) == (False, True)
    jobs = await rows(db, "select kind, payload, done from jobs")
    assert jobs == [{"kind": "rail.run", "payload": {"ticket_id": 4412, "source": "freshservice"}, "done": False}]
    assert await rows(db, "select source, external_id from webhook_dedupe") == [
        {"source": "freshservice", "external_id": "4412"}]
    assert await rows(db, "select id from runs") == []  # the worker runs the rail, not the request


async def test_a_retried_delivery_is_202_with_no_second_job(db):
    application = wired(db)
    first = await post(application, BODY, signed(BODY))
    again = await post(application, BODY, signed(BODY))            # Workflow Automator retries up to 4x
    replay = await post(application, BODY, dict(first.request.headers))  # the same signed request, replayed
    assert [x.status_code for x in (first, again, replay)] == [202, 202, 202]
    assert [x.json()["duplicate"] for x in (first, again, replay)] == [False, True, True]
    assert again.json()["job_id"] is None
    assert len(await rows(db, "select id from jobs")) == 1


async def test_concurrent_duplicate_deliveries_still_make_one_job(db):
    application = wired(db)
    out = await asyncio.gather(*(post(application, BODY, signed(BODY)) for _ in range(5)))
    assert {x.status_code for x in out} == {202}
    assert sorted(x.json()["duplicate"] for x in out) == [False, True, True, True, True]
    assert len(await rows(db, "select id from jobs where kind = 'rail.run'")) == 1


async def test_different_tickets_each_get_a_job(db):
    application = wired(db)
    for tid in (4412, 4413):
        body = json.dumps({"ticket_id": tid}).encode()
        assert (await post(application, body, signed(body))).json()["duplicate"] is False
    payloads = sorted(j["payload"]["ticket_id"] for j in await rows(db, "select payload from jobs"))
    assert payloads == [4412, 4413]


async def test_without_a_database_a_valid_delivery_is_503_not_lost_silently():
    application = app()
    del application.state.db  # model a startup/composition failure explicitly
    r = await post(application, BODY, signed(BODY))
    assert r.status_code == 503 and "database" in r.json()["detail"]

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from contextrail import repo
from contextrail.db import Database

H = "b" * 64


def fake_hash(prev: str, event: str, payload: dict, at: datetime) -> str:
    # Stand-in for audit/chain.py (T209): any deterministic function of the chain inputs.
    return hashlib.sha256(f"{prev}|{event}|{sorted(payload.items())}|{at.isoformat()}".encode()).hexdigest()


async def _run_with_hold(db):
    async with db.transaction() as c:
        run = await repo.create_run(c, source="slack", request_text="same as Rahul", requested_by="p-anil")
        await repo.upsert_action(c, run["id"], id="A1", kind="grant", target={"system": "github"},
                                 params_hash=H, verdict="HOLD", rule_id="POL-ACC-004", clause="c",
                                 approver="security-oncall", state="awaiting")
    return run


async def test_run_lifecycle_and_stage_fields(migrated_db):
    async with Database(migrated_db) as db, db.transaction() as c:
        run = await repo.create_run(c, source="email", request_text="Priya starts Monday", source_ref="4412")
        row = await repo.set_stage(c, run["id"], stage="compile", intent="onboarding", subject_id="W-8841",
                                   capsule={"subject": {"source_id": "W-8841"}}, capsule_digest="c" * 64)
        assert row["stage"] == "compile" and row["status"] == "running"
        assert row["capsule"] == {"subject": {"source_id": "W-8841"}}
        with pytest.raises(ValueError):
            await repo.set_stage(c, run["id"], status="done", verdict="ALLOW")


async def test_upsert_action_updates_in_place(migrated_db):
    async with Database(migrated_db) as db:
        run = await _run_with_hold(db)
        async with db.transaction() as c:
            await repo.set_action_state(c, run["id"], "A1", "approved")
            rows = await repo.list_actions(c, run["id"])
    assert len(rows) == 1 and rows[0]["state"] == "approved"


async def test_first_decision_wins_across_doors(migrated_db):
    async with Database(migrated_db) as db:
        run = await _run_with_hold(db)

        async def decide(channel, decision):
            async with db.transaction() as c:
                return await repo.record_approval(c, run["id"], "A1", params_hash=H, approver="p-sec",
                                                  decision=decision, channel=channel)

        results = await asyncio.gather(decide("email", "approved"), decide("teams", "refused"),
                                       decide("slack", "approved"))
        async with db.connection() as c:
            winner = await repo.get_approval(c, run["id"], "A1")
    assert sorted(results) == [False, False, True]
    assert winner["channel"] in {"email", "teams", "slack"}


async def test_claim_job_skip_locked_no_double_claim(migrated_db):
    async with Database(migrated_db, max_size=6) as db:
        async with db.transaction() as c:
            for i in range(5):
                await repo.enqueue_job(c, "rail.run", {"i": i})

        async def worker():
            async with db.transaction() as c:
                return await repo.claim_job(c)

        claimed = await asyncio.gather(*(worker() for _ in range(5)))
        ids = [j["id"] for j in claimed if j]
        assert len(ids) == 5 and len(set(ids)) == 5
        async with db.transaction() as c:
            assert await repo.claim_job(c) is None  # all leased


async def test_expired_lease_is_reclaimable_and_complete_finishes(migrated_db):
    async with Database(migrated_db) as db:
        async with db.transaction() as c:
            jid = await repo.enqueue_job(c, "approval.deadline", dedupe_key="dl:1")
            assert await repo.enqueue_job(c, "approval.deadline", dedupe_key="dl:1") is None
            job = await repo.claim_job(c, lease_seconds=60)
            assert job["id"] == jid and job["attempts"] == 1
            await c.execute("update jobs set locked_until = now() - interval '1 second' where id = %s", (jid,))
            again = await repo.claim_job(c)
            assert again["id"] == jid and again["attempts"] == 2
            await repo.complete_job(c, jid)
            assert await repo.claim_job(c) is None


async def test_fail_job_schedules_retry(migrated_db):
    async with Database(migrated_db) as db, db.transaction() as c:
        jid = await repo.enqueue_job(c, "door.update")
        await repo.claim_job(c)
        await repo.fail_job(c, jid, "slack 429", retry_in_seconds=3600)
        assert await repo.claim_job(c) is None
        row = await (await c.execute("select last_error, run_at from jobs where id = %s", (jid,))).fetchone()
        assert row["last_error"] == "slack 429" and row["run_at"] > datetime.now(UTC) + timedelta(minutes=50)


async def test_claim_job_filters_by_kind(migrated_db):
    async with Database(migrated_db) as db, db.transaction() as c:
        await repo.enqueue_job(c, "voice.call")
        assert await repo.claim_job(c, kinds=["rail.run"]) is None
        assert (await repo.claim_job(c, kinds=["voice.call"]))["kind"] == "voice.call"


async def test_concurrent_audit_appends_form_one_linear_chain(migrated_db):
    async with Database(migrated_db, max_size=8) as db:
        run = await _run_with_hold(db)

        async def append(i):
            async with db.transaction() as c:
                await repo.append_audit(c, run_id=run["id"], event="stage", payload={"i": i}, hash_fn=fake_hash)

        await asyncio.gather(*(append(i) for i in range(12)))
        async with db.connection() as c:
            rows = await (await c.execute("select prev_hash, hash from audit order by seq")).fetchall()
    assert rows[0]["prev_hash"] == repo.GENESIS
    for prev, cur in zip(rows, rows[1:], strict=False):
        assert cur["prev_hash"] == prev["hash"]  # no forks


async def test_append_audit_refuses_outside_transaction(migrated_db):
    async with Database(migrated_db) as db, db.connection() as c:
        with pytest.raises(RuntimeError):
            await repo.append_audit(c, run_id=None, event="x", payload={}, hash_fn=fake_hash)


async def test_door_messages_and_webhook_dedupe(migrated_db):
    async with Database(migrated_db) as db:
        run = await _run_with_hold(db)
        async with db.transaction() as c:
            await repo.upsert_door_message(c, run["id"], "slack", {"channel": "D1", "ts": "1.0"}, action_id="A1")
            await repo.upsert_door_message(c, run["id"], "slack", {"channel": "D1", "ts": "2.0"}, action_id="A1")
            await repo.upsert_door_message(c, run["id"], "email", {"message_id": "<m@ses>"}, action_id="A1")
            msgs = await repo.list_door_messages(c, run["id"], "A1")
            assert [m["channel"] for m in msgs] == ["email", "slack"]
            assert msgs[1]["ref"]["ts"] == "2.0"
            assert await repo.dedupe_webhook(c, "freshservice", "4412") is True
            assert await repo.dedupe_webhook(c, "freshservice", "4412") is False


async def test_refuse_cannot_be_approved_through_repo(migrated_db):
    async with Database(migrated_db) as db:
        async with db.transaction() as c:
            run = await repo.create_run(c, source="slack", request_text="x")
            await repo.upsert_action(c, run["id"], id="A9", kind="grant", target={}, params_hash=H,
                                     verdict="REFUSE", rule_id="POL-CTR-001", clause="c")
        with pytest.raises(psycopg.errors.CheckViolation):
            async with db.transaction() as c:
                await repo.set_action_state(c, run["id"], "A9", "approved")

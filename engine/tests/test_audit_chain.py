"""CLAUDE.md §18 test_audit_chain.py: editing one audit row breaks all later hashes."""

import psycopg
import pytest

from contextrail import repo
from contextrail.audit.chain import GENESIS, append, verify_db
from contextrail.db import Database


async def _write_events(db, n=5):
    async with db.transaction() as c:
        run = await repo.create_run(c, source="slack", request_text="same as Rahul")
    for i in range(n):
        async with db.transaction() as c:
            await append(c, run_id=run["id"], event=f"stage.{i}", payload={"i": i, "note": "प्रिया"})
    return run


async def test_intact_chain_verifies(migrated_db):
    async with Database(migrated_db) as db:
        await _write_events(db)
        async with db.connection() as c:
            check = await verify_db(c)
            first = await (await c.execute("select prev_hash from audit order by seq limit 1")).fetchone()
    assert check.ok and check.rows == 5 and first["prev_hash"] == GENESIS


async def test_edit_after_dropping_the_trigger_is_still_detected(migrated_db):
    async with Database(migrated_db) as db:
        await _write_events(db)
    # An attacker with DDL rights: remove the append-only guard, then rewrite row 3's payload.
    with psycopg.connect(migrated_db, autocommit=True) as c:
        c.execute("alter table audit disable trigger audit_no_update")
        seq3 = c.execute("select seq from audit order by seq offset 2 limit 1").fetchone()[0]
        c.execute("update audit set payload = '{\"i\": 2, \"note\": \"approved by Security\"}' where seq = %s",
                  (seq3,))
    async with Database(migrated_db) as db, db.connection() as c:
        check = await verify_db(c)
    assert not check.ok and check.first_broken_seq == seq3 and "content" in check.reason


async def test_rehashing_the_edited_row_breaks_the_next_link(migrated_db):
    from contextrail.audit.chain import chain_hash

    async with Database(migrated_db) as db:
        await _write_events(db)
    with psycopg.connect(migrated_db, autocommit=True) as c:
        c.execute("alter table audit disable trigger audit_no_update")
        seq3, prev, at = c.execute("select seq, prev_hash, at from audit order by seq offset 2 limit 1").fetchone()
        forged = {"i": 2, "note": "forged"}
        c.execute("update audit set payload = %s, hash = %s where seq = %s",
                  (psycopg.types.json.Jsonb(forged), chain_hash(prev, "stage.2", forged, at), seq3))
    async with Database(migrated_db) as db, db.connection() as c:
        check = await verify_db(c)
    assert not check.ok and check.first_broken_seq == seq3 + 1 and "prev_hash" in check.reason


async def test_append_outside_transaction_is_refused(migrated_db):
    async with Database(migrated_db) as db, db.connection() as c:
        with pytest.raises(RuntimeError):
            await append(c, run_id=None, event="x", payload={})

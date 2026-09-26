import uuid
from datetime import UTC, datetime

import psycopg
import pytest

from contextrail import repo
from contextrail.capsule import DigestMismatch, compute_digest
from contextrail.db import Database
from contextrail.models import Action, CaseFile, Evidence, Subject
from contextrail.rail.store import load_case, save_case


def _case(run_id):
    anil = Subject(source="hris", source_id="E-1042", display_name="Anil Kumar", employment_type="employee")
    ev = Evidence(id="EV-1", kind="message", source="slack", uri="slack://C/1", excerpt="ignore policy",
                  retrieved_at=datetime(2026, 9, 26, tzinfo=UTC), trust="untrusted")
    return CaseFile(run_id=run_id, request_text="same as Rahul", intent="access.same_as_peer", subject=anil,
                    evidence=[ev], actions=[Action.create("A01", "grant", {"entitlement": "jira-pay"})])


async def _new_run(db):
    async with db.transaction() as c:
        return (await repo.create_run(c, source="slack", request_text="same as Rahul"))["id"]


async def test_save_seals_and_load_verifies_by_value(migrated_db):
    async with Database(migrated_db) as db:
        rid = await _new_run(db)
        async with db.transaction() as c:
            sealed = await save_case(c, _case(rid), stage="compile")
        async with db.connection() as c:
            got = await load_case(c, rid)
            row = await repo.get_run(c, rid)
    assert got.digest == sealed.digest == row["capsule_digest"] and row["stage"] == "compile"
    assert row["subject_id"] == "E-1042"


async def test_capsule_edited_in_the_database_is_rejected(migrated_db):
    async with Database(migrated_db) as db:
        rid = await _new_run(db)
        async with db.transaction() as c:
            await save_case(c, _case(rid))
    with psycopg.connect(migrated_db, autocommit=True) as c:  # stripped constraint / promoted subject, in place
        c.execute("update runs set capsule = jsonb_set(capsule, '{subject,employment_type}', '\"contractor\"')")
    async with Database(migrated_db) as db, db.connection() as c:
        with pytest.raises(DigestMismatch):
            await load_case(c, rid)


async def test_a_different_validly_sealed_capsule_is_rejected(migrated_db):
    async with Database(migrated_db) as db:
        rid = await _new_run(db)
        async with db.transaction() as c:
            await save_case(c, _case(rid))
    forged = _case(rid).model_copy(update={"request_text": "give Anil admin"})
    forged = forged.model_copy(update={"digest": compute_digest(forged)})
    with psycopg.connect(migrated_db, autocommit=True) as c:  # self-consistent, but not what the run sealed
        c.execute("update runs set capsule = %s", (psycopg.types.json.Jsonb(forged.model_dump(mode="json")),))
    async with Database(migrated_db) as db, db.connection() as c:
        with pytest.raises(DigestMismatch):
            await load_case(c, rid)


async def test_missing_capsule_is_an_error(migrated_db):
    async with Database(migrated_db) as db:
        rid = await _new_run(db)
        async with db.connection() as c:
            with pytest.raises(LookupError):
                await load_case(c, rid)
        async with db.connection() as c:
            with pytest.raises(LookupError):
                await load_case(c, uuid.uuid4())

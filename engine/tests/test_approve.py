
import pytest

from contextrail import repo
from contextrail.db import Database
from contextrail.models import Action, CaseFile, Subject, Verdict, apply_verdict
from contextrail.rail.approve import dispatch_holds

ANIL = Subject(source="hris", source_id="E-1042", display_name="Anil Kumar", employment_type="employee")


def held(aid, approver="p-dana", **target):
    a = Action.create(aid, "grant", {"entitlement": aid.lower(), "subject_id": "E-1042", **target})
    return apply_verdict(a, Verdict(verdict="HOLD", rule_id="POL-ACC-004", clause_text="production repo clause",
                                    approver=approver))


def allowed(aid):
    a = Action.create(aid, "grant", {"entitlement": aid.lower(), "subject_id": "E-1042"})
    return apply_verdict(a, Verdict(verdict="ALLOW", rule_id="POL-ACC-001", clause_text="baseline clause"))


@pytest.fixture
async def run_id(migrated_db):
    async with Database(migrated_db) as db, db.transaction() as c:
        return (await repo.create_run(c, source="slack", request_text="same as Rahul"))["id"]


# --- dispatch (T100) ---------------------------------------------------------------------------------------

async def test_one_dispatch_job_per_held_action_and_never_twice(migrated_db, run_id):
    case = CaseFile(run_id=run_id, request_text="x", intent="access.same_as_peer", subject=ANIL,
                    actions=[allowed("A01"), held("A15"), held("A16", approver="p-meera")])
    async with Database(migrated_db) as db:
        async with db.transaction() as c:
            first, blockers = await dispatch_holds(c, case)
        async with db.transaction() as c:
            second, _ = await dispatch_holds(c, case)
        async with db.connection() as c:
            jobs = await (await c.execute("select kind, payload from jobs order by id")).fetchall()
    assert first == ["A15", "A16"] and second == [] and blockers == []
    assert [j["payload"]["approver"] for j in jobs] == ["p-dana", "p-meera"]
    assert all(j["kind"] == "approval.dispatch" and len(j["payload"]["params_hash"]) == 64 for j in jobs)


async def test_unresolved_approver_is_a_blocker_not_a_dispatch(migrated_db, run_id):
    case = CaseFile(run_id=run_id, request_text="x", intent="access.same_as_peer", subject=ANIL,
                    actions=[held("A16", approver="role:manager")])
    async with Database(migrated_db) as db, db.transaction() as c:
        dispatched, blockers = await dispatch_holds(c, case)
    assert dispatched == [] and "role:manager" in blockers[0]

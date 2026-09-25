"""CLAUDE.md §18 test_approval_binding.py: changing target params voids the approval."""

import pytest

from contextrail import repo
from contextrail.db import Database
from contextrail.models import Action, ActionState, CaseFile, Subject, Verdict, apply_verdict
from contextrail.rail.approve import apply_decisions

ANIL = Subject(source="hris", source_id="E-1042", display_name="Anil Kumar", employment_type="employee")
READ = {"system": "github", "repo": "northbeam/payments-core", "permission": "read", "subject_id": "E-1042"}


def held(target, aid="A15"):
    return apply_verdict(Action.create(aid, "grant", target),
                         Verdict(verdict="HOLD", rule_id="POL-ACC-004", clause_text="production repo clause",
                                 approver="p-dana"))


async def _setup(db, action):
    async with db.transaction() as c:
        run = await repo.create_run(c, source="slack", request_text="same as Rahul")
        await repo.upsert_action(c, run["id"], id=action.id, kind=action.kind, target=action.target,
                                 params_hash=action.params_hash, verdict="HOLD", rule_id="POL-ACC-004",
                                 clause="c", approver="p-dana", state="awaiting")
    return run["id"]


async def _decide(db, run_id, params_hash, decision="approved"):
    async with db.transaction() as c:
        await repo.record_approval(c, run_id, "A15", params_hash=params_hash, approver="p-dana",
                                   decision=decision, channel="teams")


@pytest.mark.parametrize(("decision", "state"), [("approved", ActionState.APPROVED), ("refused", ActionState.REFUSED)])
async def test_matching_decision_is_applied(migrated_db, decision, state):
    async with Database(migrated_db) as db:
        a = held(READ)
        rid = await _setup(db, a)
        await _decide(db, rid, a.params_hash, decision)
        case = CaseFile(run_id=rid, request_text="x", intent="i", subject=ANIL, actions=[a])
        async with db.connection() as c:
            decided, void = await apply_decisions(c, case)
    assert decided == ["A15"] and void == [] and case.action("A15").state is state


async def test_approval_for_different_params_is_void(migrated_db):
    async with Database(migrated_db) as db:
        original = held(READ)
        rid = await _setup(db, original)
        await _decide(db, rid, original.params_hash)          # Dana approved READ on payments-core
        escalated = held({**READ, "permission": "admin"})     # ...the action now asks for ADMIN
        case = CaseFile(run_id=rid, request_text="x", intent="i", subject=ANIL, actions=[escalated])
        async with db.connection() as c:
            decided, void = await apply_decisions(c, case)
    assert decided == [] and "void" in void[0] and case.action("A15").state is ActionState.AWAITING


async def test_no_decision_yet_leaves_the_action_waiting(migrated_db):
    async with Database(migrated_db) as db:
        a = held(READ)
        rid = await _setup(db, a)
        case = CaseFile(run_id=rid, request_text="x", intent="i", subject=ANIL, actions=[a])
        async with db.connection() as c:
            assert await apply_decisions(c, case) == ([], [])

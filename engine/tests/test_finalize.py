import uuid

from contextrail import repo
from contextrail.db import Database
from contextrail.models import Action, CaseFile, RunStatus, Subject, Verdict, apply_verdict
from contextrail.rail.finalize import final_status, request_receipt, tally

ANIL = Subject(source="hris", source_id="E-1042", display_name="Anil Kumar", employment_type="employee")


def act(aid, verdict, *path):
    a = Action.create(aid, "grant", {"entitlement": aid})
    v = Verdict(verdict=verdict, rule_id="POL-X", clause_text="a clause", approver="p" if verdict == "HOLD" else None)
    apply_verdict(a, v)
    for s in path:
        a.transition(s)
    return a


def case(*actions, blockers=()):
    return CaseFile(run_id=uuid.UUID(int=1), request_text="x", intent="i", subject=ANIL, actions=list(actions),
                    open_blockers=list(blockers))


def test_all_verified_is_done():
    assert final_status(case(act("A1", "ALLOW", "executed", "verified"))) is RunStatus.DONE


def test_anything_waiting_is_awaiting_approval():
    c = case(act("A1", "ALLOW", "executed", "verified"), act("A2", "HOLD"), act("A3", "REFUSE"))
    assert final_status(c) is RunStatus.AWAITING_APPROVAL


def test_a_refusal_makes_the_outcome_partial_not_done():
    c = case(act("A1", "ALLOW", "executed", "verified"), act("A2", "HOLD", "approved", "executed", "verified"),
             act("A3", "REFUSE"))
    assert final_status(c) is RunStatus.PARTIAL


def test_failed_unknown_or_unexecuted_or_blocked_is_partial():
    assert final_status(case(act("A1", "ALLOW", "executed", "failed"))) is RunStatus.PARTIAL
    assert final_status(case(act("A1", "ALLOW", "unknown"))) is RunStatus.PARTIAL
    assert final_status(case(act("A1", "ALLOW"))) is RunStatus.PARTIAL  # blocked from executing
    assert final_status(case(act("A1", "ALLOW", "executed", "verified"), blockers=["stale"])) is RunStatus.PARTIAL


def test_tally():
    c = case(act("A1", "ALLOW", "executed", "verified"), act("A2", "HOLD"), act("A3", "REFUSE"),
             act("A4", "ALLOW", "executed", "failed"))
    assert tally(c) == {"allow": 2, "hold": 1, "refuse": 1, "verified": 1, "failed": 1}


async def test_receipt_is_requested_once_per_outcome(migrated_db):
    async with Database(migrated_db) as db:
        async with db.transaction() as c:
            run = await repo.create_run(c, source="slack", request_text="x", run_id=uuid.UUID(int=1))
        c1 = case(act("A1", "ALLOW", "executed", "verified"), act("A2", "HOLD"))
        async with db.transaction() as c:
            first = await request_receipt(c, c1, final_status(c1))
            again = await request_receipt(c, c1, final_status(c1))
        c2 = case(act("A1", "ALLOW", "executed", "verified"), act("A2", "HOLD", "approved", "executed", "verified"))
        async with db.transaction() as c:
            later = await request_receipt(c, c2, final_status(c2))
    assert run and first is not None and again is None and later is not None

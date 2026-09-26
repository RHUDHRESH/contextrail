"""The whole rail against real Postgres and FIXTURE connectors: P0-3, P0-6, P0-8 end to end."""

from collections import Counter
from datetime import UTC, datetime, timedelta

import psycopg

from contextrail import repo
from contextrail.audit.chain import verify_db
from contextrail.fixtures import load, subject_from_record
from contextrail.models import Action, CaseFile, RunStatus
from contextrail.policy.engine import apply_decision
from contextrail.rail.store import load_case, save_case

STAGES = ["discover", "compile", "govern", "plan", "handoff", "approve", "execute", "verify", "finalize"]


async def _actions(deps, run_id):
    async with deps.db.connection() as c:
        return {a["id"]: a for a in await repo.list_actions(c, run_id)}


async def _start(runner, text, **kw):
    rid = await runner.start(source="slack", request_text=text, requested_by="p-anil")
    return rid, await runner.run(rid, **kw)


async def test_same_as_rahul_end_to_end_13_2_1(rail):
    runner, deps = rail
    rid, status = await _start(runner, "Give Anil the same access as Rahul Mehta")
    assert status is RunStatus.AWAITING_APPROVAL
    acts = await _actions(deps, rid)
    grants = [a for a in acts.values() if a["kind"] == "grant"]
    assert Counter(a["verdict"] for a in grants) == {"ALLOW": 13, "HOLD": 2, "REFUSE": 1}
    assert Counter(a["state"] for a in acts.values()) == {"verified": 15, "awaiting": 2, "refused": 1}
    assert all(a["verified_at"] for a in acts.values() if a["state"] == "verified")
    assert all(a["idempotency_key"] for a in acts.values())
    held = (await deps.registry.get("entitlements").read({"subject_id": "E-1042"}))["holdings"]
    assert "jira-pay" in held and "looker-risk-dashboards" not in held      # granted, and old team revoked
    assert "aws-payments-prod-admin" not in held and "postman-enterprise-seat" not in held  # refused / held
    gh = await deps.registry.get("github").read({"repo": "northbeam/payments-api"})
    assert gh["collaborators"]["anil-k-nb"] == "read"


async def test_every_stage_ran_in_order_audited_and_streamed(rail):
    runner, deps = rail
    rid, _ = await _start(runner, "Give Anil the same access as Rahul Mehta")
    assert [e.stage.value for e in deps.events.history(rid)] == STAGES
    async with deps.db.connection() as c:
        events = [r["event"] for r in await (await c.execute(
            "select event from audit where run_id = %s order by seq", (rid,))).fetchall()]
        check = await verify_db(c)
        jobs = Counter(r["kind"] for r in await (await c.execute("select kind from jobs")).fetchall())
    assert events == ["run.created", *[f"stage.{s}" for s in STAGES]]
    assert check.ok
    assert jobs == {"approval.dispatch": 2, "receipt.build": 1}


async def test_injection_both_halves(rail):
    """CLAUDE.md §18 test_injection_both_halves / P0-8: the planted message IS in the case AND the REFUSE holds."""
    runner, deps = rail
    rid, _ = await _start(runner, "Give Anil the same access as Rahul Mehta")
    async with deps.db.connection() as c:
        run = await repo.get_run(c, rid)
    evidence = {e["id"]: e for e in run["capsule"]["evidence"]}
    planted = evidence["EV-slk_payments_admin_override"]
    assert planted["trust"] == "untrusted" and "ignore the Access Control Standard" in planted["excerpt"]
    admin = next(a for a in (await _actions(deps, rid)).values() if a["target"]["entitlement"] == "aws-payments-prod-admin")
    assert (admin["verdict"], admin["state"], admin["rule_id"]) == ("REFUSE", "refused", "POL-ACC-003")


async def test_contractor_everything_refuses_production_credentials_terminally(rail):
    runner, deps = rail
    rid, status = await _start(runner, "Priya starts Monday, give her everything she needs")
    acts = {a["target"]["entitlement"]: a for a in (await _actions(deps, rid)).values()}
    assert status is RunStatus.AWAITING_APPROVAL
    assert acts["slack-general"]["state"] == "verified"
    assert (acts["gh-perception-sdk-read"]["state"], acts["gh-perception-sdk-read"]["approver"]) == ("awaiting", "p-dana")
    assert (acts["aws-perception-prod-credentials"]["rule_id"], acts["aws-perception-prod-credentials"]["state"]) == (
        "POL-CTR-001", "refused")
    async with deps.db.connection() as c:
        run = await repo.get_run(c, rid)
    assert any("Marc Liu" in e["excerpt"] for e in run["capsule"]["evidence"])  # Priya's injection retrieved too


async def test_ambiguous_peer_stops_at_needs_input_then_a_pick_completes(rail):
    runner, deps = rail
    rid, status = await _start(runner, "Give Anil the same access as Rahul")
    assert status is RunStatus.NEEDS_INPUT
    assert deps.events.history(rid)[-1].message.startswith("Which Rahul?")
    async with deps.db.connection() as c:
        assert (await repo.get_run(c, rid))["capsule"] is None  # nothing compiled on a guess
    status = await runner.run(rid, peer_id="E-0007")
    assert status is RunStatus.AWAITING_APPROVAL


async def test_resume_after_approvals_finishes_partial_because_of_the_refusal(rail):
    runner, deps = rail
    rid, _ = await _start(runner, "Give Anil the same access as Rahul Mehta")
    acts = await _actions(deps, rid)
    async with deps.db.transaction() as c:
        for a in acts.values():
            if a["state"] == "awaiting":
                await repo.record_approval(c, rid, a["id"], params_hash=a["params_hash"],
                                           approver=a["approver"], decision="approved", channel="slack")
    status = await runner.resume(rid)
    assert status is RunStatus.PARTIAL
    assert Counter(a["state"] for a in (await _actions(deps, rid)).values()) == {"verified": 17, "refused": 1}
    held = (await deps.registry.get("entitlements").read({"subject_id": "E-1042"}))["holdings"]
    assert "postman-enterprise-seat" in held and "aws-payments-prod-admin" not in held


async def test_tampered_capsule_halts_the_run_at_handoff(rail, migrated_db):
    runner, deps = rail
    rid, _ = await _start(runner, "Give Anil the same access as Rahul Mehta")
    with psycopg.connect(migrated_db, autocommit=True) as c:  # promote the refused row to allowed, in the capsule
        c.execute("""update runs set capsule = jsonb_set(capsule, '{constraints}', '["forged"]') where id = %s""",
                  (rid,))
    assert await runner.resume(rid) is RunStatus.FAILED
    async with deps.db.connection() as c:
        events = [r["event"] for r in await (await c.execute(
            "select event from audit where run_id = %s order by seq", (rid,))).fetchall()]
    assert events[-1] == "capsule.digest_mismatch"


async def test_questions_are_routed_not_run(rail):
    runner, _ = rail
    _, status = await _start(runner, "What happened to my access request?")
    assert status is RunStatus.DONE


async def test_a_time_boxed_action_is_stored_with_its_expiry(rail):
    """T068: the expiry a rule puts on an action (POL-EMG-001, 4 h) reaches the actions table, not only the capsule."""
    runner, deps = rail
    rid = await runner.start(source="slack", request_text="incident access to payments dashboards",
                             requested_by="p-anil")
    anil = subject_from_record(next(p for p in load("hris")["people"] if p["source_id"] == "E-1042"))
    now = datetime(2026, 9, 26, 10, 0, tzinfo=UTC)
    action = Action.create("A01", "grant", {"origin": "incident", "incident_id": "INC-4412", "system": "datadog",
                                            "permission": "viewer"})
    apply_decision(action, deps.engine.decide(action, anil), now=now)
    case = CaseFile(run_id=rid, request_text="incident access", intent="access.incident", subject=anil,
                    actions=[action])
    async with deps.db.transaction() as c:
        await save_case(c, case)
        await runner._sync_actions(c, case)
    stored = (await _actions(deps, rid))["A01"]
    assert (stored["verdict"], stored["expires_at"]) == ("HOLD", now + timedelta(hours=4))
    async with deps.db.connection() as c:  # and the sealed capsule round-trips it with its digest intact (P5)
        assert (await load_case(c, rid)).action("A01").expires_at == now + timedelta(hours=4)

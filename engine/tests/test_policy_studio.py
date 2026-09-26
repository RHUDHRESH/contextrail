"""Policy Studio (checklist T072): re-evaluate a governed run with one rule held out, and report what would move.

The case files here are built the way the rail builds them (Govern + Plan over FIXTURE records), so the stored
verdicts are real ones. Nothing in the Studio writes: it answers "what if this rule did not exist?".
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from contextrail.capsule import seal
from contextrail.fixtures import load, subject_from_record
from contextrail.models import CaseFile
from contextrail.policy.approvers import StaticDirectory
from contextrail.policy.engine import PolicyEngine
from contextrail.policy.loader import load_rules
from contextrail.policy.studio import UnknownRule, simulate_hold_out
from contextrail.rail import govern, plan
from contextrail.rail.compile import CompileInputs, role_entry

NOW = datetime(2026, 9, 26, 10, 0, tzinfo=UTC)
DIRECTORY = StaticDirectory(roster={"security-oncall": ["p-dana", "p-omar"]}, managers={"E-0301": "p-meera"})
ENGINE = PolicyEngine(load_rules(), DIRECTORY)


def _record(pid):
    return next(p for p in load("hris")["people"] if p["source_id"] == pid)


def governed_case(subject_id, *, intent, request_text, peer_id=None, requested_by="p-anil", engine=ENGINE):
    """A sealed case file, governed and planned exactly as the runner does it."""
    ents = load("entitlements")
    rec = _record(subject_id)
    subject = subject_from_record(rec)
    peer = subject_from_record(_record(peer_id)) if peer_id else None
    inputs = CompileInputs(subject_holdings=ents["holdings"].get(subject_id, []),
                           peer_holdings=ents["holdings"].get(peer_id, []) if peer_id else [],
                           catalog=ents["catalog"], role=role_entry(subject.role))
    gov = govern.evaluate(govern.build_candidates(intent, request_text, subject, inputs, peer), subject, engine,
                          role=inputs.role, requested_by=requested_by, now=NOW)
    ordered = plan.build_plan(gov, subject, rec, inputs, engine, requested_by=requested_by)
    return seal(CaseFile(run_id=uuid4(), request_text=request_text, intent=intent, subject=subject, peer=peer,
                         actions=[g.action for g in ordered])), inputs


@pytest.fixture(scope="module")
def rahul_case():
    return governed_case("E-1042", peer_id="E-0007", intent="access.same_as_peer",
                         request_text="Give Anil the same access as Rahul Mehta")


def studio(case_inputs, rule_id, engine=ENGINE):
    case, inputs = case_inputs
    return simulate_hold_out(case, engine, rule_id, role=inputs.role, requested_by="p-anil")


def row(report, entitlement):
    return next(r for r in report.actions if r.label == entitlement)


def test_every_action_is_examined_and_the_baseline_matches_the_run(rahul_case):
    r = studio(rahul_case, "POL-ACC-003")
    assert r.blast_radius.examined == 18                        # 16 grants + 2 transfer revocations
    assert r.blast_radius.before == {"allow": 15, "hold": 2, "refuse": 1}
    assert r.blast_radius.drift == 0 and not any(a.drift for a in r.actions)
    assert r.simulation is True and r.capsule_digest == rahul_case[0].digest


def test_holding_out_acc_003_would_hand_anil_production_admin(rahul_case):
    r = studio(rahul_case, "POL-ACC-003")
    admin = row(r, "aws-payments-prod-admin")
    assert (admin.before.verdict, admin.before.rule_id) == ("REFUSE", "POL-ACC-003")
    assert (admin.after.verdict, admin.after.rule_id) == ("ALLOW", "POL-ACC-002")   # mirrored access now decides
    assert admin.change == "loosened"
    b = r.blast_radius
    assert (b.changed, b.unblocked, b.loosened, b.tightened) == (1, 1, 1, 0)
    assert b.after == {"allow": 16, "hold": 2, "refuse": 0}
    assert "1 refused action would no longer be refused" in b.headline


def test_holding_out_acc_004_skips_the_security_approval(rahul_case):
    r = studio(rahul_case, "POL-ACC-004")
    core = row(r, "gh-payments-core-read")
    assert (core.before.verdict, core.before.approver, core.after.verdict) == ("HOLD", "p-dana", "ALLOW")
    assert (r.blast_radius.changed, r.blast_radius.loses_approval) == (1, 1)
    assert "1 held action would skip its approver" in r.blast_radius.headline


def test_holding_out_the_baseline_rule_moves_no_outcome_only_the_quoted_rule(rahul_case):
    r = studio(rahul_case, "POL-ACC-001")
    moved = [a for a in r.actions if a.change != "none"]
    assert moved and all(a.change == "same_verdict" and a.after.rule_id == "POL-ACC-002" for a in moved)
    assert r.blast_radius.before == r.blast_radius.after
    assert (r.blast_radius.unblocked, r.blast_radius.loses_approval, r.blast_radius.tightened) == (0, 0, 0)


def test_holding_out_off_001_leaves_old_team_access_default_denied(rahul_case):
    r = studio(rahul_case, "POL-OFF-001")
    revokes = [a for a in r.actions if a.kind == "revoke"]
    assert [(a.before.verdict, a.after.verdict, a.after.rule_id) for a in revokes] == [
        ("ALLOW", "REFUSE", "DEFAULT-DENY")] * 2
    assert (r.blast_radius.tightened, r.blast_radius.newly_refused) == (2, 2)


def test_a_rule_that_decided_nothing_here_changes_nothing(rahul_case):
    r = studio(rahul_case, "POL-DAT-001")
    assert r.blast_radius.changed == 0 and all(a.change == "none" for a in r.actions)
    assert "changes no verdict in this run" in r.blast_radius.headline


def test_a_terminal_rule_can_be_simulated_and_says_so():
    priya = governed_case("W-8841", intent="onboarding", request_text="Priya starts Monday, give her everything",
                          requested_by="p-marc")
    r = simulate_hold_out(priya[0], ENGINE, "POL-CTR-001", role=priya[1].role, requested_by="p-marc")
    creds = row(r, "aws-perception-prod-credentials")
    assert (creds.before.rule_id, creds.before.terminal) == ("POL-CTR-001", True)
    assert (creds.after.verdict, creds.after.rule_id) == ("REFUSE", "DEFAULT-DENY")  # default deny still holds
    assert r.rule_terminal is True and creds.change == "same_verdict"


def test_drift_is_reported_when_todays_rules_disagree_with_the_run():
    older = PolicyEngine([r for r in load_rules() if r.id != "POL-ACC-001"], DIRECTORY)  # governed before ACC-001
    case = governed_case("E-1042", peer_id="E-0007", intent="access.same_as_peer", request_text="same as Rahul",
                         engine=older)
    r = studio(case, "POL-ACC-005")
    assert r.blast_radius.drift > 0
    drifted = [a for a in r.actions if a.drift]
    assert all(a.stored.rule_id == "POL-ACC-002" and a.before.rule_id == "POL-ACC-001" for a in drifted)
    assert r.blast_radius.headline.startswith(f"{r.blast_radius.drift} actions are decided differently today")


def test_the_studio_changes_nothing_in_the_case_it_reads(rahul_case):
    case = rahul_case[0]
    snapshot = case.model_dump(mode="json")
    studio(rahul_case, "POL-ACC-003")
    assert case.model_dump(mode="json") == snapshot


def test_unknown_rule_is_rejected(rahul_case):
    with pytest.raises(UnknownRule):
        studio(rahul_case, "POL-XYZ-999")

"""The shipped rules, one behaviour at a time (CLAUDE.md §18 test_policy_rules.py). Every verdict quotes its clause."""

import pytest

from contextrail.models import Action, Subject
from contextrail.policy.approvers import StaticDirectory
from contextrail.policy.engine import PolicyEngine, check_decision
from contextrail.policy.loader import load_rules

DIRECTORY = StaticDirectory(roster={"security-oncall": ["p-dana"], "incident-commander": ["p-omar"]},
                            managers={"E-0301": "p-meera"})


@pytest.fixture(scope="module")
def engine():
    return PolicyEngine(load_rules(), DIRECTORY)


def person(**kw):
    base = {"source": "hris", "source_id": "E-1042", "display_name": "Anil Kumar", "employment_type": "employee",
            "role": "payments-engineer", "team": "payments", "seniority": "mid", "manager_id": "E-0301"}
    return Subject(**(base | kw))


ANIL = person()
PRIYA = person(source_id="W-8841", display_name="Priya Raghunathan", employment_type="contractor",
               role="contract-engineer", team="perception", seniority=None, sow_repos=["northbeam/perception-sdk"])
VENDOR = person(source_id="V-0012", display_name="Acme Integrations", employment_type="vendor", seniority=None)


def grant(**target):
    return Action.create("A1", "grant", target)


def decide(engine, action, subject, **kw):
    return engine.decide(action, subject, **kw).verdict


# --- POL-CTR-001 (T061) ------------------------------------------------------------------------------------

@pytest.mark.parametrize("rc", ["production_credential", "production_admin", "production_db", "customer_pii_export"])
@pytest.mark.parametrize("who", [PRIYA, VENDOR])
def test_ctr_001_contractors_and_vendors_never_get_production_access(engine, who, rc):
    v = decide(engine, grant(system="aws", resource_class=rc), who)
    assert (v.verdict, v.rule_id, v.terminal) == ("REFUSE", "POL-CTR-001", True)
    assert "must never receive production credentials" in v.clause_text


def test_ctr_001_is_terminal_even_if_another_rule_would_allow(engine):
    # Even with a senior-sounding role, a contractor cannot be approved into production.
    v = decide(engine, grant(system="aws", resource_class="production_admin"), PRIYA.model_copy(
        update={"seniority": "principal"}))
    assert v.rule_id == "POL-CTR-001" and v.terminal


def test_ctr_001_does_not_apply_to_employees(engine):
    v = decide(engine, grant(system="aws", resource_class="production_credential"), ANIL)
    assert v.rule_id != "POL-CTR-001"


# --- POL-ACC-001 (T062) ------------------------------------------------------------------------------------

PAYMENTS_ROLE = {"id": "payments-engineer", "baseline": ["gh-payments-api-read", "slack-payments", "jira-pay"]}


def test_acc_001_role_baseline_is_allowed(engine):
    v = decide(engine, grant(system="github", entitlement="gh-payments-api-read"), ANIL, role=PAYMENTS_ROLE)
    assert (v.verdict, v.rule_id) == ("ALLOW", "POL-ACC-001")
    assert "baseline" in v.clause_text


def test_acc_001_outside_baseline_is_not_allowed_by_this_rule(engine):
    v = decide(engine, grant(system="datadog", entitlement="dd-admin"), ANIL, role=PAYMENTS_ROLE)
    assert v.rule_id != "POL-ACC-001"


def test_acc_001_without_a_role_record_allows_nothing(engine):
    v = decide(engine, grant(entitlement="gh-payments-api-read"), ANIL)  # role catalogue not loaded
    assert (v.verdict, v.rule_id) == ("REFUSE", "DEFAULT-DENY")


# --- POL-ACC-002 (T063) ------------------------------------------------------------------------------------

def mirrored(**target):
    return grant(origin="same_as_peer", **target)


def test_acc_002_peer_item_in_requesters_role_scope_is_allowed(engine):
    v = decide(engine, mirrored(system="pagerduty", entitlement="pd-payments", role_scope=["payments-engineer"]),
               ANIL)
    assert (v.verdict, v.rule_id) == ("ALLOW", "POL-ACC-002")


def test_acc_002_peer_item_outside_requesters_role_is_refused_with_clause(engine):
    # Rahul (the peer) holds a risk-analytics dashboard; Anil's role does not cover it.
    v = decide(engine, mirrored(system="looker", entitlement="looker-risk", role_scope=["risk-analyst"]), ANIL)
    assert (v.verdict, v.rule_id) == ("REFUSE", "POL-ACC-002")
    assert "receiving person's own role" in v.clause_text


def test_acc_002_only_governs_mirrored_requests(engine):
    v = decide(engine, grant(system="looker", entitlement="looker-risk", role_scope=["risk-analyst"]), ANIL)
    assert v.rule_id != "POL-ACC-002"


# --- POL-ACC-003 (T064) ------------------------------------------------------------------------------------

def test_acc_003_non_senior_is_refused_admin_rights(engine):
    v = decide(engine, grant(system="aws", entitlement="aws-payments-prod-admin", resource_class="production_admin"),
               ANIL)
    assert (v.verdict, v.rule_id) == ("REFUSE", "POL-ACC-003")
    assert "senior engineers and above" in v.clause_text


def test_acc_003_senior_is_held_for_named_security_approver(engine):
    rahul = person(source_id="E-0007", display_name="Rahul Mehta", seniority="senior")
    v = decide(engine, grant(system="aws", resource_class="admin"), rahul)
    assert (v.verdict, v.rule_id, v.approver) == ("HOLD", "POL-ACC-003", "p-dana")


def test_acc_003_unknown_seniority_is_refused_not_assumed(engine):
    v = decide(engine, grant(system="aws", resource_class="admin"), person(seniority=None))
    assert v.verdict == "REFUSE"


# --- POL-ACC-004 (T065) ------------------------------------------------------------------------------------

def repo(name, permission="read", tags=()):
    return grant(system="github", repo=name, permission=permission, repo_tags=list(tags))


def test_acc_004_employee_untagged_repo_allowed(engine):
    v = decide(engine, repo("northbeam/payments-docs", "write"), ANIL)
    assert (v.verdict, v.rule_id) == ("ALLOW", "POL-ACC-004")


def test_acc_004_employee_production_repo_held_for_security(engine):
    v = decide(engine, repo("northbeam/payments-core", tags=["production"]), ANIL)
    assert (v.verdict, v.rule_id, v.approver) == ("HOLD", "POL-ACC-004", "p-dana")
    assert "tagged 'production'" in v.clause_text


def test_acc_004_contractor_sow_repo_read_only_held_when_production(engine):
    v = decide(engine, repo("northbeam/perception-sdk", tags=["production"]), PRIYA)
    assert (v.verdict, v.approver) == ("HOLD", "p-dana")


@pytest.mark.parametrize("action", [
    repo("northbeam/payments-core"),                          # not in the SOW
    repo("northbeam/perception-sdk", "write"),                # in the SOW but not read-only
    repo("northbeam/perception-sdk", "admin", ["production"]),
])
def test_acc_004_contractor_outside_sow_or_not_read_is_refused(engine, action):
    v = decide(engine, action, PRIYA)
    assert (v.verdict, v.rule_id) == ("REFUSE", "POL-ACC-004")


# --- POL-ACC-005 (T066) ------------------------------------------------------------------------------------

def test_acc_005_paid_seat_held_for_the_named_manager(engine):
    v = decide(engine, grant(system="postman", entitlement="postman-enterprise-seat", seat_cost_usd=49), ANIL,
               run={"requested_by": "p-anil"})
    assert (v.verdict, v.rule_id, v.approver) == ("HOLD", "POL-ACC-005", "p-meera")
    assert "paid SaaS tool" in v.clause_text


def test_acc_005_hold_outranks_a_baseline_allow(engine):
    # A seat can be on the role baseline and still cost money: the manager still approves.
    v = decide(engine, grant(system="figma", entitlement="figma-seat", seat_cost_usd=15), ANIL,
               role={"baseline": ["figma-seat"]})
    assert (v.verdict, v.rule_id) == ("HOLD", "POL-ACC-005")


def test_acc_005_free_tool_is_not_held(engine):
    v = decide(engine, grant(system="slack", entitlement="slack-payments", seat_cost_usd=0), ANIL,
               role={"baseline": ["slack-payments"]})
    assert (v.verdict, v.rule_id) == ("ALLOW", "POL-ACC-001")


def test_acc_005_manager_who_requested_cannot_approve(engine):
    v = decide(engine, grant(system="postman", seat_cost_usd=49), ANIL, run={"requested_by": "p-meera"})
    assert v.approver == "role:manager"  # visibly unresolved -> blocker, never self-approval


# --- POL-OFF-001 (T069) ------------------------------------------------------------------------------------

def test_off_001_old_team_access_is_revoked_on_transfer(engine):
    revoke = Action.create("R1", "revoke", {"system": "looker", "entitlement": "looker-risk", "origin": "transfer",
                                            "previous_team": "risk-analytics"})
    v = decide(engine, revoke, ANIL)
    assert (v.verdict, v.rule_id) == ("ALLOW", "POL-OFF-001")
    assert "within 4 hours" in v.clause_text


def test_off_001_other_revocations_are_not_blanket_allowed(engine):
    revoke = Action.create("R2", "revoke", {"system": "github", "entitlement": "gh-payments-api-read"})
    assert decide(engine, revoke, ANIL).rule_id == "DEFAULT-DENY"


# --- POL-SOD-001 (T070) ------------------------------------------------------------------------------------

H = "a" * 64


def sod(engine, approver, requested_by="p-anil", beneficiary="p-anil"):
    return check_decision(engine, ANIL, action_id="A7", params_hash=H, approver=approver,
                          requested_by=requested_by, beneficiary=beneficiary)


def test_sod_001_independent_approver_is_allowed(engine):
    v = sod(engine, "p-dana")
    assert (v.verdict, v.rule_id) == ("ALLOW", "POL-SOD-001")


@pytest.mark.parametrize(("approver", "requested_by", "beneficiary"), [
    ("p-anil", "p-anil", "p-anil"),     # approving your own request
    ("p-meera", "p-meera", "p-anil"),   # manager raised it, manager approves it
    ("p-anil", "p-meera", "p-anil"),    # beneficiary approves a request raised for them
])
def test_sod_001_requester_or_beneficiary_cannot_approve(engine, approver, requested_by, beneficiary):
    v = sod(engine, approver, requested_by, beneficiary)
    assert (v.verdict, v.rule_id, v.terminal) == ("REFUSE", "POL-SOD-001", True)
    assert "void" in v.clause_text


def test_sod_001_unattributable_request_is_refused(engine):
    assert sod(engine, "p-dana", requested_by=None).verdict == "REFUSE"


# --- POL-DAT-001 (T067) ------------------------------------------------------------------------------------

ANALYST = person(source_id="E-0612", display_name="Aisha Bello", role="data-analyst", team="data-analytics",
                 seniority="senior")
RAW = {"system": "snowflake", "entitlement": "warehouse-customers-raw", "permission": "read", "data_class": "raw_pii"}


def raw_pii(**extra):
    return grant(**RAW, masked_view="warehouse-customers-masked", **extra)


def test_dat_001_analytics_team_may_read_raw_customer_pii(engine):
    d = engine.decide(raw_pii(), ANALYST)
    assert (d.verdict.verdict, d.verdict.rule_id) == ("ALLOW", "POL-DAT-001")
    assert d.alternative is None  # nothing to offer instead of an allowed grant


@pytest.mark.parametrize("who", [ANIL, PRIYA, person(team=None)])
def test_dat_001_everyone_else_is_refused_and_offered_the_masked_view(engine, who):
    d = engine.decide(raw_pii(), who)
    assert (d.verdict.verdict, d.verdict.rule_id) == ("REFUSE", "POL-DAT-001")
    assert "masked view" in d.verdict.clause_text
    assert d.alternative == "warehouse-customers-masked"


def test_dat_001_the_alternative_is_recorded_alongside_and_never_changes_the_verdict(engine):
    offered = engine.decide(raw_pii(), ANIL)
    bare = engine.decide(grant(**RAW), ANIL)  # the catalogue names no masked view
    assert bare.alternative is None
    assert offered.verdict == bare.verdict
    # The same rule with its `alternative` removed decides byte-for-byte the same.
    stripped = [r.model_copy(update={"alternative": None}) if r.id == "POL-DAT-001" else r for r in engine.rules]
    assert PolicyEngine(stripped, DIRECTORY).decide(raw_pii(), ANIL).verdict == offered.verdict


def test_dat_001_masked_data_is_left_to_the_ordinary_access_rules(engine):
    masked = grant(system="snowflake", entitlement="warehouse-customers-masked", permission="read", data_class="masked")
    d = engine.decide(masked, ANIL, role={"baseline": ["warehouse-customers-masked"]})
    assert (d.verdict.verdict, d.verdict.rule_id) == ("ALLOW", "POL-ACC-001")
    assert engine.decide(masked, ANIL).verdict.rule_id == "DEFAULT-DENY"  # not on the baseline: still default deny


def test_dat_001_offers_nothing_when_another_rule_decides(engine):
    # Mirrored from a peer but outside Anil's role: POL-ACC-002 is quoted, so its (absent) alternative is used.
    d = engine.decide(raw_pii(origin="same_as_peer", role_scope=["data-analyst"]), ANIL)
    assert (d.verdict.verdict, d.verdict.rule_id, d.alternative) == ("REFUSE", "POL-ACC-002", None)

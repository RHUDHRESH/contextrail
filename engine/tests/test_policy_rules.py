"""The shipped rules, one behaviour at a time (CLAUDE.md §18 test_policy_rules.py). Every verdict quotes its clause."""

import pytest

from contextrail.models import Action, Subject
from contextrail.policy.approvers import StaticDirectory
from contextrail.policy.engine import PolicyEngine
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

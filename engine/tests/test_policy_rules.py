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

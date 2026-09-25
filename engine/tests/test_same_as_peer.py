"""P0-3 at the policy level (CLAUDE.md §2, §18): "same access as Rahul" for Anil gives 16 items -> 13 / 2 / 1.

Candidates are the peer's entitlements minus the requester's current ones (checklist T095 will do this in the
rail). Each candidate is judged by the shipped rules against ANIL's record and ANIL's role, never Rahul's.
"""

from collections import Counter

import pytest

from contextrail.fixtures import load, subject_from_record
from contextrail.models import Action
from contextrail.policy.approvers import StaticDirectory
from contextrail.policy.engine import PolicyEngine
from contextrail.policy.loader import load_rules

DIRECTORY = StaticDirectory(roster={"security-oncall": ["p-dana", "p-omar"]}, managers={"E-0301": "p-meera"})


def _person(pid):
    return next(p for p in load("hris")["people"] if p["source_id"] == pid)


@pytest.fixture(scope="module")
def outcome():
    ents, roles = load("entitlements"), load("roles")["roles"]
    anil = subject_from_record(_person("E-1042"))
    held = set(ents["holdings"]["E-1042"])
    candidates = [e for e in ents["holdings"]["E-0007"] if e not in held]
    engine = PolicyEngine(load_rules(), DIRECTORY)
    verdicts = {}
    for i, ent in enumerate(candidates, 1):
        action = Action.create(f"A{i:02d}", "grant", {**ents["catalog"][ent], "entitlement": ent,
                                                      "origin": "same_as_peer"})
        verdicts[ent] = engine.decide(action, anil, role=roles[anil.role], run={"requested_by": "p-anil"}).verdict
    return candidates, verdicts


def test_sixteen_candidates(outcome):
    candidates, _ = outcome
    assert len(candidates) == 16


def test_thirteen_two_one(outcome):
    _, verdicts = outcome
    assert Counter(v.verdict for v in verdicts.values()) == {"ALLOW": 13, "HOLD": 2, "REFUSE": 1}


def test_the_holds_name_security_and_the_manager(outcome):
    _, v = outcome
    assert (v["gh-payments-core-read"].rule_id, v["gh-payments-core-read"].approver) == ("POL-ACC-004", "p-dana")
    assert (v["postman-enterprise-seat"].rule_id, v["postman-enterprise-seat"].approver) == ("POL-ACC-005", "p-meera")


def test_the_refusal_is_production_admin_with_clause(outcome):
    _, v = outcome
    refused = [e for e, x in v.items() if x.verdict == "REFUSE"]
    assert refused == ["aws-payments-prod-admin"]
    assert v["aws-payments-prod-admin"].rule_id == "POL-ACC-003"
    assert "senior engineers and above" in v["aws-payments-prod-admin"].clause_text


def test_old_team_items_are_revoked_on_transfer():
    ents = load("entitlements")
    anil = subject_from_record(_person("E-1042"))
    engine = PolicyEngine(load_rules(), DIRECTORY)
    # Old-team access = what Anil holds that his new role does not cover (the Plan stage's definition, T097).
    old_team = [e for e in ents["holdings"]["E-1042"] if anil.role not in ents["catalog"][e]["role_scope"]]
    assert old_team == ["looker-risk-dashboards", "slack-risk-analytics"]
    for ent in old_team:
        revoke = Action.create(f"R-{ent}", "revoke", {**ents["catalog"][ent], "entitlement": ent, "origin": "transfer"})
        assert engine.decide(revoke, anil).verdict.rule_id == "POL-OFF-001"


def test_catalog_is_well_formed():
    ents, roles = load("entitlements"), load("roles")["roles"]
    known_roles = {p["role"] for p in load("hris")["people"]}
    for ent, target in ents["catalog"].items():
        assert "*" not in target["role_scope"], f"{ent}: no wildcards; the evaluator has no wildcard semantics"
        assert set(target["role_scope"]) <= known_roles | set(roles), f"{ent}: unknown role in scope"
        if target["system"] == "github":
            assert {"repo", "permission", "repo_tags"} <= set(target), ent
    for pid, held in ents["holdings"].items():
        assert set(held) <= set(ents["catalog"]), pid
    for role in roles.values():
        assert set(role["baseline"]) <= set(ents["catalog"])

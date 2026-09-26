"""Clause integrity (checklist T060): every verdict quotes its rule verbatim, and every clause has a known origin."""

import re
from pathlib import Path

import pytest

from contextrail.models import Action, Subject
from contextrail.policy.approvers import StaticDirectory
from contextrail.policy.engine import DEFAULT_DENY_CLAUSE, DEFAULT_DENY_ID, PolicyEngine
from contextrail.policy.loader import load_rules

ROOT = Path(__file__).resolve().parents[2]
RULES = {r.id: r for r in load_rules()}
ENGINE = PolicyEngine(list(RULES.values()), StaticDirectory(roster={"security-oncall": ["p-dana"]},
                                                            managers={"E-0301": "p-meera"}))

ANIL = Subject(source="hris", source_id="E-1042", display_name="Anil Kumar", employment_type="employee",
               role="payments-engineer", team="payments", seniority="mid", manager_id="E-0301")
PRIYA = ANIL.model_copy(update={"source_id": "W-8841", "employment_type": "contractor", "seniority": None,
                                "sow_repos": ["northbeam/perception-sdk"]})
CASES = [
    (Action.create("A1", "grant", {"resource_class": "production_credential"}), PRIYA, {}),
    (Action.create("A2", "grant", {"entitlement": "jira-pay"}), ANIL, {"baseline": ["jira-pay"]}),
    (Action.create("A3", "grant", {"origin": "same_as_peer", "role_scope": ["risk-analyst"]}), ANIL, {}),
    (Action.create("A4", "grant", {"resource_class": "production_admin"}), ANIL, {}),
    (Action.create("A5", "grant", {"system": "github", "repo": "northbeam/core", "repo_tags": ["production"]}),
     ANIL, {}),
    (Action.create("A6", "grant", {"seat_cost_usd": 49}), ANIL, {}),
    (Action.create("A7", "revoke", {"origin": "transfer"}), ANIL, {}),
    (Action.create("A8", "grant", {"system": "unknown-tool"}), ANIL, {}),
]


@pytest.mark.parametrize(("action", "subject", "role"), CASES)
def test_every_verdict_quotes_its_deciding_rule_byte_for_byte(action, subject, role):
    v = ENGINE.decide(action, subject, role=role).verdict
    expected = DEFAULT_DENY_CLAUSE if v.rule_id == DEFAULT_DENY_ID else RULES[v.rule_id].clause_text
    assert v.clause_text == expected
    assert v.clause_text.encode("utf-8") == expected.encode("utf-8")


def test_the_cases_exercise_every_shipped_rule_except_sod():
    decided = {ENGINE.decide(a, s, role=r).verdict.rule_id for a, s, r in CASES}
    assert set(RULES) - {"POL-SOD-001"} <= decided  # SOD is exercised through check_decision (test_policy_rules)


def _stage1_corpus_text() -> str:
    corpus = (ROOT / "src" / "lib" / "contextrail" / "data" / "corpus.ts").read_text(encoding="utf-8")
    return " ".join(re.findall(r"D\(`(.*?)`\)", corpus, flags=re.DOTALL))


def _authored_in_d011() -> set[str]:
    text = (ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
    section = text.split("## D-011", 1)[1]
    authored = section.split("**Authored clauses.**", 1)[1].split("\n\n", 1)[0]
    return {f"POL-{m}" for m in re.findall(r"\b([A-Z]{3}-\d{3})\b", authored)}


def test_every_clause_is_verbatim_from_stage1_or_declared_authored():
    corpus = _stage1_corpus_text()
    authored = _authored_in_d011()
    undeclared = [rid for rid, r in RULES.items() if r.clause_text not in corpus and rid not in authored]
    assert not undeclared, f"clauses with no known origin: {undeclared}"
    assert RULES["POL-CTR-001"].clause_text in corpus  # the headline refusal is verbatim policy text

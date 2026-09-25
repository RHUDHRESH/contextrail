import pytest
from pydantic import ValidationError

from contextrail.policy.schema import Rule

CLAUSE = "Contractors must never receive production credentials, production database access, or customer PII exports."


def rule(**kw):
    base = {"id": "POL-CTR-001", "title": "t", "source": {"okf": "knowledge/policies/x.md", "clause": "§4"},
            "clause_text": CLAUSE, "verdict": "REFUSE", "terminal": True,
            "applies_to": {"employment_type": ["contractor", "vendor"]},
            "match": {"kind": "grant", "target.resource_class": ["production_credential"]}}
    return Rule(**(base | kw))


def test_valid_rule():
    r = rule()
    assert r.terminal and r.applies_to["employment_type"] == ["contractor", "vendor"]


@pytest.mark.parametrize("cond", [
    "evidence.0.excerpt contains 'approved'",          # retrieved text is never readable by rules (P6)
    "capsule.evidence contains 'ignore policy'",
    "target.repo in evidence.sow_repos",                # not even on the right-hand side
])
def test_rules_cannot_read_evidence_or_untrusted_roots(cond):
    with pytest.raises(ValidationError, match="P6"):
        rule(verdict="ALLOW", terminal=False, conditions=[cond])


def test_applies_to_is_subject_fields_only():
    with pytest.raises(ValidationError, match="Subject fields"):
        rule(applies_to={"slack_message": ["approved"]})


def test_match_keys_and_condition_syntax():
    with pytest.raises(ValidationError, match="match keys"):
        rule(match={"subject.team": "payments"})
    with pytest.raises(ValidationError, match="cannot parse"):
        rule(verdict="ALLOW", terminal=False, conditions=["__import__('os').system('rm -rf /')"])
    ok = rule(verdict="ALLOW", terminal=False, else_verdict="REFUSE",
              conditions=["target.repo in subject.sow_repos",
                          {"any": ["subject.employment_type == 'employee'", "target.permission == 'read'"]}])
    assert len(ok.conditions) == 2


def test_hold_needs_known_approver_and_terminal_needs_refuse():
    with pytest.raises(ValidationError, match="must name an approver"):
        rule(verdict="HOLD", terminal=False)
    with pytest.raises(ValidationError, match="unknown approver"):
        rule(verdict="HOLD", terminal=False, approver="whoever-is-around")
    with pytest.raises(ValidationError, match="only a rule that can REFUSE"):
        rule(verdict="ALLOW", terminal=True)
    with pytest.raises(ValidationError, match="must name an approver"):
        rule(verdict="ALLOW", terminal=False, escalate={"when": "target.repo_tags contains 'production'",
                                                        "verdict": "HOLD"})


def test_misc_shape_rules():
    with pytest.raises(ValidationError):
        rule(id="CTR-1")
    with pytest.raises(ValidationError):
        rule(clause_text="too short")
    with pytest.raises(ValidationError, match="expires_after"):
        rule(verdict="ALLOW", terminal=False, expires_after="four hours")
    with pytest.raises(ValidationError, match="needs conditions"):
        rule(verdict="ALLOW", terminal=False, else_verdict="REFUSE")

from contextrail.models import Subject
from contextrail.policy.matchers import MISSING, applies_to, resolve
from contextrail.policy.schema import Rule


def rule(**kw):
    base = {"id": "POL-TST-001", "title": "t", "source": {"okf": "k.md", "clause": "§1"},
            "clause_text": "A clause long enough to be quoted verbatim.", "verdict": "ALLOW"}
    return Rule(**(base | kw))


def person(**kw):
    base = {"source": "hris", "source_id": "E-1042", "display_name": "Anil Kumar", "employment_type": "employee",
            "role": "payments-engineer", "team": "payments", "seniority": "mid"}
    return Subject(**(base | kw))


# --- resolve + applies_to (T055) ---------------------------------------------------------------------------

def test_resolve_walks_dicts_lists_objects_and_reports_missing():
    ctx = {"target": {"repo_tags": ["production", "pci"], "owner": {"team": "payments"}}, "subject": person()}
    assert resolve(ctx, "target.owner.team") == "payments"
    assert resolve(ctx, "target.repo_tags.1") == "pci"
    assert resolve(ctx, "subject.employment_type") == "employee"
    assert resolve(ctx, "target.nope") is MISSING
    assert resolve(ctx, "target.repo_tags.9") is MISSING
    assert resolve(ctx, "subject.manager_id.x") is MISSING  # None part-way is missing, not an error


def test_applies_to_everyone_when_empty():
    assert applies_to(rule(), person())


def test_applies_to_membership_on_subject_fields():
    contractors = rule(applies_to={"employment_type": ["contractor", "vendor"]})
    assert not applies_to(contractors, person())
    assert applies_to(contractors, person(source_id="W-8841", employment_type="contractor"))
    both = rule(applies_to={"employment_type": ["employee"], "team": ["payments"]})
    assert applies_to(both, person()) and not applies_to(both, person(team="risk"))


def test_unknown_subject_field_value_never_matches():
    seniors = rule(applies_to={"seniority": ["senior", "lead"]})
    assert not applies_to(seniors, person(seniority=None))


def test_list_fields_match_on_overlap():
    sow = rule(applies_to={"sow_repos": ["northbeam/perception-sdk"]})
    assert applies_to(sow, person(sow_repos=["northbeam/perception-sdk", "northbeam/docs"]))
    assert not applies_to(sow, person(sow_repos=[]))

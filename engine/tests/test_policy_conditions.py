import pytest

from contextrail.policy.conditions import evaluate, evaluate_all

CTX = {
    "subject": {"employment_type": "contractor", "sow_repos": ["northbeam/perception-sdk"], "seniority": None},
    "target": {"repo": "northbeam/perception-sdk", "permission": "read", "repo_tags": ["production", "pci"],
               "seat_cost_usd": 49, "free": 0},
    "run": {"requested_by": "p-anil"},
    "decision": {"approver": "p-anil"},
}


@pytest.mark.parametrize(("expr", "expected"), [
    ("target.repo in subject.sow_repos", True),
    ("target.repo not in subject.sow_repos", False),
    ("target.permission == 'read'", True),
    ("target.permission != 'read'", False),
    ("target.permission in ['read', 'triage']", True),
    ("target.repo_tags contains 'production'", True),
    ("target.repo_tags not contains 'production'", False),
    ("target.seat_cost_usd > 0", True),
    ("target.free > 0", False),
    ("target.seat_cost_usd <= 49", True),
    ("run.requested_by == decision.approver", True),
    ("run.requested_by != decision.approver", False),
])
def test_operators(expr, expected):
    assert evaluate(expr, CTX) is expected


@pytest.mark.parametrize("expr", [
    "target.nope == 'x'", "target.nope != 'x'",           # missing: both equality forms are false
    "subject.seniority in ['senior']", "subject.seniority not in ['senior']",  # None is unknown, not a value
    "target.permission > 3",                              # type mismatch is false, not an exception
    "target.seat_cost_usd contains 'x'",                  # contains on a number
    "target.repo in 42",
])
def test_unknown_or_mistyped_is_false_never_an_error(expr):
    assert evaluate(expr, CTX) is False


def test_any_all_blocks_nest():
    assert evaluate({"any": ["target.permission == 'write'", "subject.employment_type == 'contractor'"]}, CTX)
    assert not evaluate({"all": ["target.permission == 'read'", {"any": ["target.free > 0", "target.nope == 1"]}]},
                        CTX)
    assert evaluate_all([], CTX)  # no conditions -> holds


def test_booleans_are_not_numbers():
    assert evaluate("target.flag > 0", {"target": {"flag": True}}) is False


def test_unparseable_expression_is_false_not_eval():
    assert evaluate("__import__('os').system('echo pwned')", CTX) is False

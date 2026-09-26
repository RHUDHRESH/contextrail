from contextrail.models import Action, Subject
from contextrail.policy.approvers import StaticDirectory, is_unresolved, resolve_approver
from contextrail.policy.engine import PolicyEngine
from contextrail.policy.schema import Rule

ANIL = Subject(source="hris", source_id="E-1042", display_name="Anil Kumar", employment_type="employee",
               role="payments-engineer", team="payments", manager_id="E-0301")
DIR = StaticDirectory(roster={"security-oncall": ["p-dana", "p-omar"]}, managers={"E-0301": "p-meera"})


def test_manager_resolves_through_the_subject_record():
    assert resolve_approver(DIR, "manager", ANIL) == "p-meera"


def test_roster_role_resolves_to_first_on_call():
    assert resolve_approver(DIR, "security-oncall", ANIL) == "p-dana"


def test_requester_is_never_their_own_approver():
    assert resolve_approver(DIR, "security-oncall", ANIL, requested_by="p-dana") == "p-omar"
    assert resolve_approver(DIR, "manager", ANIL, requested_by="p-meera") == "role:manager"


def test_unknown_role_or_missing_manager_stays_visibly_unresolved():
    assert resolve_approver(DIR, "finance", ANIL) == "role:finance"
    no_mgr = ANIL.model_copy(update={"manager_id": None})
    assert resolve_approver(DIR, "manager", no_mgr) == "role:manager"
    assert is_unresolved("role:finance") and not is_unresolved("p-dana")


def test_engine_names_a_person_on_hold():
    seat = Rule(id="POL-TST-005", title="seat", source={"okf": "k.md", "clause": "§5"},
                clause_text="Paid SaaS seats require the requester's manager to approve.",
                match={"kind": "grant"}, conditions=["target.seat_cost_usd > 0"], verdict="HOLD", approver="manager")
    v = PolicyEngine([seat], DIR).decide(Action.create("A1", "grant", {"seat_cost_usd": 49}), ANIL,
                                        run={"requested_by": "p-anil"}).verdict
    assert (v.verdict, v.approver) == ("HOLD", "p-meera")

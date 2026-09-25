import inspect

from contextrail.models import Action, Subject
from contextrail.policy.engine import DEFAULT_DENY_ID, PolicyEngine
from contextrail.policy.schema import Rule

CL = "A clause long enough to be quoted verbatim: {}."


def R(rid, **kw):
    return Rule(**({"id": rid, "title": rid, "source": {"okf": "k.md", "clause": "§1"},
                    "clause_text": CL.format(rid), "verdict": "ALLOW"} | kw))


ANIL = Subject(source="hris", source_id="E-1042", display_name="Anil Kumar", employment_type="employee",
               role="payments-engineer", team="payments", seniority="mid")
PRIYA = Subject(source="hris", source_id="W-8841", display_name="Priya Raghunathan", employment_type="contractor",
                sow_repos=["northbeam/perception-sdk"])


def grant(**t):
    return Action.create("A1", "grant", t)


# --- precedence and default deny (T058) --------------------------------------------------------------------

def test_default_deny_when_no_rule_allows():
    d = PolicyEngine([]).decide(grant(system="github"), ANIL)
    assert (d.verdict.verdict, d.verdict.rule_id, d.fired) == ("REFUSE", DEFAULT_DENY_ID, ())


def test_explicit_allow():
    d = PolicyEngine([R("POL-TST-001", match={"kind": "grant"})]).decide(grant(), ANIL)
    assert d.verdict.verdict == "ALLOW" and d.verdict.rule_id == "POL-TST-001"


def test_refuse_beats_hold_beats_allow_and_terminal_refuse_is_chosen_first():
    rules = [R("POL-TST-001"),
             R("POL-TST-002", verdict="HOLD", approver="manager"),
             R("POL-TST-003", verdict="REFUSE"),
             R("POL-TST-004", verdict="REFUSE", terminal=True)]
    v = PolicyEngine(rules).decide(grant(), ANIL).verdict
    assert (v.verdict, v.rule_id, v.terminal) == ("REFUSE", "POL-TST-004", True)
    v2 = PolicyEngine(rules[:2]).decide(grant(), ANIL).verdict
    assert (v2.verdict, v2.approver) == ("HOLD", "role:manager")  # no directory -> visibly unresolved


def test_most_senior_approver_wins_among_holds():
    rules = [R("POL-TST-001", verdict="HOLD", approver="manager"),
             R("POL-TST-002", verdict="HOLD", approver="security-oncall")]
    v = PolicyEngine(rules).decide(grant(), ANIL).verdict
    assert (v.rule_id, v.approver) == ("POL-TST-002", "role:security-oncall")


def test_escalate_and_else_verdict():
    repo = R("POL-TST-004", match={"kind": "grant", "target.system": "github"},
             conditions=[{"any": ["subject.employment_type == 'employee'",
                                  {"all": ["target.repo in subject.sow_repos", "target.permission == 'read'"]}]}],
             escalate={"when": "target.repo_tags contains 'production'", "verdict": "HOLD",
                       "approver": "security-oncall"},
             else_verdict="REFUSE")
    eng = PolicyEngine([repo])
    assert eng.decide(grant(system="github", repo="northbeam/docs", permission="write"), ANIL).verdict.verdict == "ALLOW"
    held = eng.decide(grant(system="github", repo="northbeam/payments-core", repo_tags=["production"]), ANIL).verdict
    assert (held.verdict, held.approver) == ("HOLD", "role:security-oncall")
    sow = grant(system="github", repo="northbeam/perception-sdk", permission="read", repo_tags=["production"])
    assert eng.decide(sow, PRIYA).verdict.verdict == "HOLD"
    off_sow = grant(system="github", repo="northbeam/payments-core", permission="read")
    assert eng.decide(off_sow, PRIYA).verdict.verdict == "REFUSE"
    write = grant(system="github", repo="northbeam/perception-sdk", permission="write")
    assert eng.decide(write, PRIYA).verdict.verdict == "REFUSE"


def test_rules_that_do_not_apply_are_silent_and_fired_is_explained():
    rules = [R("POL-TST-001", applies_to={"employment_type": ["contractor"]}, verdict="REFUSE"),
             R("POL-TST-002", match={"kind": "grant"})]
    d = PolicyEngine(rules).decide(grant(), ANIL)
    assert d.verdict.verdict == "ALLOW" and [o.rule.id for o in d.fired] == ["POL-TST-002"]


def test_disabled_rules_are_held_out_for_policy_studio():
    rules = [R("POL-TST-001"), R("POL-TST-002", verdict="REFUSE")]
    eng = PolicyEngine(rules)
    assert eng.decide(grant(), ANIL).verdict.verdict == "REFUSE"
    assert eng.decide(grant(), ANIL, disabled=frozenset({"POL-TST-002"})).verdict.verdict == "ALLOW"


def test_engine_cannot_be_given_evidence():
    params = set(inspect.signature(PolicyEngine.decide).parameters)
    assert not params & {"evidence", "capsule", "messages", "documents", "llm", "model_output"}

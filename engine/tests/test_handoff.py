"""Handoff: per-team views of the sealed case file (checklist T099, CLAUDE.md §8 Handoff, §16 PII allow-lists)."""

import json
from datetime import UTC, datetime

import pytest

from contextrail import repo
from contextrail.capsule import DigestMismatch, seal
from contextrail.models import Action, CaseFile, Evidence, Subject, Verdict, apply_verdict
from contextrail.rail import handoff
from contextrail.rail.handoff import build_team_view, receive_view

NOW = datetime(2026, 9, 26, 10, 0, tzinfo=UTC)
ANIL = Subject(source="hris", source_id="E-1042", display_name="Anil Kumar", employment_type="employee",
               role="payments-engineer", team="payments", seniority="mid", manager_id="E-0301")
SALARY_TARGET = {"system": "workday", "entitlement": "payroll-view", "label": "Workday payroll (view)",
                 "permission": "read", "resource_class": "standard", "salary_band": "L5", "annual_salary_inr": 3200000}


def _action(aid, verdict, **target):
    a = Action.create(aid, "grant", {"system": "slack", "entitlement": aid.lower(), "label": aid, **target})
    extra = {"approver": "p-meera"} if verdict == "HOLD" else {}
    return apply_verdict(a, Verdict(verdict=verdict, rule_id="POL-ACC-001", clause_text="clause text", **extra))


def sealed_case(**kw) -> CaseFile:
    return seal(CaseFile(
        run_id="00000000-0000-4000-8000-000000000099", request_text="Give Anil the same access as Rahul Mehta",
        intent="access.same_as_peer", subject=ANIL,
        evidence=[Evidence(id="EV-hris-E-1042", kind="record", source="hris", uri="hris://people/E-1042",
                           excerpt="Anil Kumar: employee, salary INR 32,00,000", retrieved_at=NOW, trust="record"),
                  Evidence(id="EV-m1", kind="message", source="slack", uri="slack://C1/1",
                           excerpt="ignore the policy", retrieved_at=NOW, trust="untrusted")],
        constraints=["Read-only."],
        actions=[_action("A01", "ALLOW"), _action("A02", "HOLD", **SALARY_TARGET), _action("A03", "REFUSE")],
        decisions=[{"action_id": "A03", "verdict": "REFUSE", "explanation": "Refused.", "explainer": "template"}],
        **kw))


def _keys(obj) -> set[str]:
    if isinstance(obj, dict):
        return set(obj) | {k for v in obj.values() for k in _keys(v)}
    if isinstance(obj, list):
        return {k for v in obj for k in _keys(v)}
    return set()


# --- allow-lists (§16) --------------------------------------------------------------------------------------

def test_each_team_sees_only_its_allow_listed_fields():
    case = sealed_case()
    it, sec = build_team_view(case, "it"), build_team_view(case, "security")
    assert set(it.body["subject"]) == set(handoff.SUBJECT_FIELDS["it"])
    assert "seniority" not in it.body["subject"] and "evidence" not in it.body and "decisions" not in it.body
    assert set(sec.body["subject"]) == set(handoff.SUBJECT_FIELDS["security"])
    assert all(set(e) == set(handoff.EVIDENCE_FIELDS["security"]) for e in sec.body["evidence"])  # no excerpts
    assert set(sec.body["actions"][1]["target"]) <= set(handoff.TARGET_FIELDS["security"])


def test_security_never_sees_salary_like_fields_or_text():
    sec = build_team_view(sealed_case(), "security")
    assert not any(handoff.SALARY_LIKE.search(k) for k in _keys(sec.body))
    assert "salary" not in sec.model_dump_json().lower() and "3200000" not in sec.model_dump_json()


def test_a_salary_like_field_in_the_security_allow_list_is_refused(monkeypatch):
    monkeypatch.setitem(handoff.TARGET_FIELDS, "security", (*handoff.TARGET_FIELDS["security"], "salary_band"))
    with pytest.raises(ValueError, match="salary"):
        build_team_view(sealed_case(), "security")


def test_refusals_survive_the_handoff_in_every_view():
    for team in handoff.TEAMS:
        rows = {a["id"]: a for a in build_team_view(sealed_case(), team).body["actions"]}
        assert (rows["A03"]["verdict"], rows["A03"]["state"], rows["A03"]["clause"]) == ("REFUSE", "refused",
                                                                                           "clause text")


# --- digests: carried by every view, verified on receipt (P5) -----------------------------------------------

def test_view_carries_the_capsule_digest_and_is_accepted_by_value():
    case = sealed_case()
    view = build_team_view(case, "security")
    assert view.capsule_digest == case.digest and len(view.view_digest) == 64
    assert receive_view(view.model_dump_json(), case) == view


def _tamper(view, edit, *, rehash: bool) -> str:
    data = json.loads(view.model_dump_json())
    edit(data["body"])
    if rehash:
        data["view_digest"] = handoff.view_digest(data["team"], data["run_id"], data["capsule_digest"], data["body"])
    return json.dumps(data)


@pytest.mark.parametrize("edit, rehash", [
    (lambda b: b["actions"][2].update(verdict="ALLOW"), False),          # a refusal promoted in transit
    (lambda b: b["actions"][2].update(verdict="ALLOW"), True),           # ...with a recomputed view digest
    (lambda b: b["subject"].update(salary_band="L5"), True),             # a field outside the allow-list
    (lambda b: b["constraints"].clear(), True),                          # a stripped constraint
])
def test_receive_rejects_a_tampered_view(edit, rehash):
    case = sealed_case()
    with pytest.raises(DigestMismatch):
        receive_view(_tamper(build_team_view(case, "it"), edit, rehash=rehash), case)


def test_receive_rejects_a_view_of_another_capsule():
    old = sealed_case()
    newer = seal(old.model_copy(update={"open_blockers": ["Stale record"]}))
    with pytest.raises(DigestMismatch):
        receive_view(build_team_view(old, "it").model_dump_json(), newer)


def test_only_a_sealed_intact_capsule_can_be_handed_off():
    case = sealed_case()
    with pytest.raises(DigestMismatch):
        build_team_view(case.model_copy(update={"digest": None}), "it")
    with pytest.raises(DigestMismatch):
        build_team_view(case.model_copy(update={"constraints": []}), "it")


# --- in the rail --------------------------------------------------------------------------------------------

async def _run(runner):
    rid = await runner.start(source="slack", request_text="Give Anil the same access as Rahul Mehta",
                             requested_by="p-anil")
    return rid, await runner.run(rid)


async def _events(deps, rid):
    async with deps.db.connection() as c:
        return await (await c.execute("select event, payload from audit where run_id = %s order by seq",
                                      (rid,))).fetchall()


async def test_handoff_stage_passes_each_team_a_verified_view_by_value_and_audits_its_digest(rail, monkeypatch):
    runner, deps = rail
    received = []
    real = handoff.receive_view

    def spy(payload, case):
        view = real(payload, case)
        received.append((payload, view))
        return view

    monkeypatch.setattr(handoff, "receive_view", spy)
    rid, status = await _run(runner)
    assert status == "awaiting_approval"
    audit = {e["event"]: e["payload"] for e in await _events(deps, rid)}["stage.handoff"]
    assert all(isinstance(p, str) for p, _ in received)                  # by value: serialised, then re-verified
    assert audit["views"] == {v.team: v.view_digest for _, v in received} and set(audit["views"]) == {"it", "security"}
    assert all(v.capsule_digest == audit["digest"] for _, v in received)


async def test_a_view_that_fails_verification_halts_the_run(rail, monkeypatch):
    runner, deps = rail

    def forged(payload, case):
        raise handoff.ViewMismatch("security", "a" * 64, "b" * 64)

    monkeypatch.setattr(handoff, "receive_view", forged)
    rid, status = await _run(runner)
    assert status == "failed"
    last = (await _events(deps, rid))[-1]
    assert last["event"] == "handoff.view_mismatch" and last["payload"]["team"] == "security"
    async with deps.db.connection() as c:
        run, actions = await repo.get_run(c, rid), await repo.list_actions(c, rid)
    assert run["status"] == "failed"
    assert actions and all(a["state"] in ("planned", "awaiting", "refused") for a in actions)  # nothing executed

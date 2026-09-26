from collections import Counter
from datetime import UTC, datetime

import pytest

from contextrail.connectors.fixture import FixtureEntitlements, FixtureHRIS
from contextrail.connectors.state import FixtureState
from contextrail.fixtures import subject_from_record
from contextrail.policy.engine import PolicyEngine
from contextrail.policy.loader import load_rules
from contextrail.rail.compile import gather_inputs
from contextrail.rail.govern import build_candidates, evaluate
from contextrail.rail.plan import build_plan, transfer_revokes
from contextrail.seed import approver_directory

NOW = datetime(2026, 9, 26, 10, 0, tzinfo=UTC)


@pytest.fixture
async def anil_case(tmp_path):
    hs, es = FixtureState("hris", directory=tmp_path), FixtureState("entitlements", directory=tmp_path)
    hs.reset()
    es.reset()
    hris, ents = FixtureHRIS(hs), FixtureEntitlements(es)
    rec, peer = await hris.read({"source_id": "E-1042"}), await hris.read({"source_id": "E-0007"})
    inputs = await gather_inputs(rec, peer, entitlements=ents, rules=[], now=NOW)
    anil = subject_from_record(rec)
    engine = PolicyEngine(load_rules(), approver_directory())
    gov = evaluate(build_candidates("access.same_as_peer", "same as Rahul", anil, inputs, subject_from_record(peer)),
                   anil, engine, role=inputs.role, requested_by="p-anil")
    return anil, rec, inputs, engine, gov


async def test_transfer_revokes_old_team_access_only(anil_case):
    anil, rec, inputs, _, _ = anil_case
    revokes = transfer_revokes(anil, rec, inputs)
    assert [r.target["entitlement"] for r in revokes] == ["looker-risk-dashboards", "slack-risk-analytics"]
    assert all(r.kind == "revoke" and r.target["previous_team"] == "risk-analytics" for r in revokes)


async def test_no_transfer_no_revokes(anil_case):
    anil, rec, inputs, _, _ = anil_case
    assert transfer_revokes(anil, {**rec, "previous_team": None}, inputs) == []


async def test_plan_orders_grants_revokes_holds_refusals_and_keeps_the_refusal(anil_case):
    anil, rec, inputs, engine, gov = anil_case
    plan = build_plan(gov, anil, rec, inputs, engine, requested_by="p-anil")
    shape = [(g.action.kind, g.verdict.verdict) for g in plan]
    assert len(plan) == 18
    assert shape[:13] == [("grant", "ALLOW")] * 13
    assert shape[13:15] == [("revoke", "ALLOW")] * 2
    assert shape[15:17] == [("grant", "HOLD")] * 2
    assert shape[17] == ("grant", "REFUSE")                       # visible, last, not deleted
    assert plan[17].action.target["entitlement"] == "aws-payments-prod-admin"
    assert Counter(g.verdict.rule_id for g in plan[13:15]) == {"POL-OFF-001": 2}


# --- explanations (T098, template path) --------------------------------------------------------------------

async def test_template_explanations_for_holds_and_refusals_only(anil_case):
    from contextrail.rail.plan import TemplateExplainer, explanations

    anil, rec, inputs, engine, gov = anil_case
    plan = build_plan(gov, anil, rec, inputs, engine, requested_by="p-anil")
    before = [(g.action.id, g.verdict.verdict, g.action.state) for g in plan]
    ex = explanations(plan, TemplateExplainer({"p-dana": "Dana Osei", "p-meera": "Meera Iyer"}))
    assert [e["verdict"] for e in ex] == ["HOLD", "HOLD", "REFUSE"] and all(e["explainer"] == "template" for e in ex)
    texts = [e["explanation"] for e in ex]
    assert texts[0].startswith("Held for Dana Osei:") and texts[1].startswith("Held for Meera Iyer:")
    assert texts[2].startswith("Refused under POL-ACC-003:")
    assert [(g.action.id, g.verdict.verdict, g.action.state) for g in plan] == before  # words change nothing

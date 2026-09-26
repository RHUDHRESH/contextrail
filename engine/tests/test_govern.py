from collections import Counter
from datetime import UTC, datetime, timedelta

import pytest

from contextrail.connectors.fixture import FixtureEntitlements, FixtureHRIS
from contextrail.connectors.state import FixtureState
from contextrail.fixtures import subject_from_record
from contextrail.models import Action
from contextrail.policy.engine import PolicyEngine
from contextrail.policy.loader import load_rules
from contextrail.rail.compile import gather_inputs
from contextrail.rail.govern import build_candidates, evaluate
from contextrail.seed import approver_directory

NOW = datetime(2026, 9, 26, 10, 0, tzinfo=UTC)


@pytest.fixture
async def world(tmp_path):
    hris_s, ent_s = FixtureState("hris", directory=tmp_path), FixtureState("entitlements", directory=tmp_path)
    hris_s.reset()
    ent_s.reset()
    return FixtureHRIS(hris_s), FixtureEntitlements(ent_s)


async def _inputs(world, sid, peer_id=None):
    hris, ents = world
    rec = await hris.read({"source_id": sid})
    peer = await hris.read({"source_id": peer_id}) if peer_id else None
    inputs = await gather_inputs(rec, peer, entitlements=ents, rules=[], now=NOW)
    return subject_from_record(rec), (subject_from_record(peer) if peer else None), inputs


# --- candidates (T095) -------------------------------------------------------------------------------------

async def test_same_as_peer_candidates_are_peer_minus_current(world):
    anil, rahul, inputs = await _inputs(world, "E-1042", "E-0007")
    acts = build_candidates("access.same_as_peer", "Give Anil the same access as Rahul", anil, inputs, rahul)
    assert len(acts) == 16 and len({a.id for a in acts}) == 16
    assert all(a.target["origin"] == "same_as_peer" and a.target["subject_id"] == "E-1042" for a in acts)
    assert "okta-sso" not in {a.target["entitlement"] for a in acts}  # already held


async def test_onboarding_everything_includes_what_policy_must_refuse(world):
    priya, _, inputs = await _inputs(world, "W-8841")
    acts = build_candidates("onboarding", "Priya starts Monday, give her everything she needs", priya, inputs)
    ents = [a.target["entitlement"] for a in acts]
    assert ents == ["slack-general", "gh-perception-sdk-read", "aws-perception-prod-credentials"]


async def test_onboarding_without_everything_is_baseline_plus_sow(world):
    priya, _, inputs = await _inputs(world, "W-8841")
    acts = build_candidates("onboarding", "Priya starts Monday", priya, inputs)
    assert [a.target["entitlement"] for a in acts] == ["slack-general", "gh-perception-sdk-read"]


# --- evaluate through policy (T096) ------------------------------------------------------------------------

@pytest.fixture
def engine():
    return PolicyEngine(load_rules(), approver_directory())


async def test_anil_same_as_rahul_is_13_2_1_through_govern(world, engine):
    anil, rahul, inputs = await _inputs(world, "E-1042", "E-0007")
    acts = build_candidates("access.same_as_peer", "same as Rahul", anil, inputs, rahul)
    gov = evaluate(acts, anil, engine, role=inputs.role, requested_by="p-anil")
    assert Counter(g.verdict.verdict for g in gov) == {"ALLOW": 13, "HOLD": 2, "REFUSE": 1}
    states = Counter(g.action.state for g in gov)
    assert states == {"planned": 13, "awaiting": 2, "refused": 1}
    assert all(g.action.rule_id and g.action.clause for g in gov)


async def test_priya_everything_is_allow_hold_refuse_with_terminal_ctr_001(world, engine):
    priya, _, inputs = await _inputs(world, "W-8841")
    acts = build_candidates("onboarding", "give her everything", priya, inputs)
    gov = {g.action.target["entitlement"]: g.verdict for g in evaluate(acts, priya, engine, role=inputs.role,
                                                                       requested_by="p-marc")}
    assert gov["slack-general"].verdict == "ALLOW"
    assert (gov["gh-perception-sdk-read"].verdict, gov["gh-perception-sdk-read"].approver) == ("HOLD", "p-dana")
    prod = gov["aws-perception-prod-credentials"]
    assert (prod.verdict, prod.rule_id, prod.terminal) == ("REFUSE", "POL-CTR-001", True)


async def test_govern_stamps_the_rule_time_box_on_the_action(world, engine):
    anil, _, inputs = await _inputs(world, "E-1042")
    incident = Action.create("A01", "grant", {"origin": "incident", "incident_id": "INC-4412", "system": "datadog",
                                              "permission": "viewer", "entitlement": "datadog-payments-viewer"})
    baseline = Action.create("A02", "grant", {**inputs.catalog["jira-pay"], "entitlement": "jira-pay"})
    gov = evaluate([incident, baseline], anil, engine, role=inputs.role, requested_by="p-anil", now=NOW)
    assert (gov[0].action.rule_id, gov[0].action.expires_at) == ("POL-EMG-001", NOW + timedelta(hours=4))
    assert (gov[1].action.verdict, gov[1].action.expires_at) == ("ALLOW", None)  # no rule time-boxes a baseline grant

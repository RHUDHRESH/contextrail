from datetime import UTC, datetime

import pytest

from contextrail.connectors.fixture import FixtureEntitlements, FixtureHRIS
from contextrail.connectors.state import FixtureState
from contextrail.fixtures import subject_from_record
from contextrail.rail.compile import gather_inputs
from contextrail.rail.govern import build_candidates

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


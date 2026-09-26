"""Assets (T130, P2): read a laptop and assign it to a person for onboarding, verified by read-back (P3).

api.freshservice.com, Assets (valid for Freshservice signups before 2026-03-31):
GET /api/v2/assets/[display_id] -> `asset`;  PUT /api/v2/assets/[display_id] -> `asset`;
`user_id` is "ID of the associated user (Used By)". Newer tenants use the Freshservice ITAM API instead, which
documents no user assignment field (D-017).
"""

import httpx
import pytest
from _fs_mock import API_KEY, DOMAIN, FakeTenant, ok

from contextrail.connectors.base import ConnectorError, UnknownOutcome
from contextrail.connectors.freshservice import FreshserviceClient, FreshserviceConnector
from contextrail.connectors.state import FixtureState
from contextrail.settings import Settings

PRIYA = 5000008841
ASSET = ("GET", "/api/v2/assets/101")
PUT = ("PUT", "/api/v2/assets/101")


def laptop(user_id=None) -> dict:
    return {"id": 9500000101, "display_id": 101, "name": "MacBook Pro 14", "asset_tag": "NB-LAP-0101",
            "user_id": user_id, "usage_type": "permanent"}


async def test_get_asset_by_display_id():
    tenant = FakeTenant({ASSET: ok({"asset": laptop()})})
    async with FreshserviceClient(DOMAIN, API_KEY, transport=tenant.transport) as fs:
        assert await fs.get_asset(101) == laptop()


async def test_update_asset_puts_only_the_fields_given():
    tenant = FakeTenant({PUT: ok({"asset": laptop(PRIYA)})})
    async with FreshserviceClient(DOMAIN, API_KEY, transport=tenant.transport) as fs:
        assert (await fs.update_asset(101, {"user_id": PRIYA}))["user_id"] == PRIYA
    assert tenant.body() == {"user_id": PRIYA}


def live(tmp_path, tenant: FakeTenant) -> FreshserviceConnector:
    return FreshserviceConnector(Settings(_env_file=None, fs_domain=DOMAIN, fs_api_key=API_KEY),
                                 state=FixtureState("freshservice", directory=tmp_path), transport=tenant.transport)


async def test_assigning_writes_then_reads_back_and_says_verified(tmp_path):
    state = {"asset": laptop()}
    tenant = FakeTenant({ASSET: lambda r: ok({"asset": state["asset"]}),
                         PUT: lambda r: (state.update(asset=laptop(PRIYA)), ok({"asset": state["asset"]}))[1]})
    out = await live(tmp_path, tenant).assign_asset(101, PRIYA)
    assert (out.mode, out.user_id, out.replayed, out.verified) == ("LIVE", PRIYA, False, True)
    assert [r.method for r in tenant.requests] == ["GET", "PUT", "GET"]


async def test_an_asset_already_with_that_person_is_not_written_again(tmp_path):
    tenant = FakeTenant({ASSET: ok({"asset": laptop(PRIYA)})})
    out = await live(tmp_path, tenant).assign_asset(101, PRIYA)
    assert (out.replayed, out.verified) == (True, True) and [r.method for r in tenant.requests] == ["GET"]


async def test_a_200_that_changed_nothing_is_not_verified(tmp_path):
    tenant = FakeTenant({ASSET: ok({"asset": laptop()}), PUT: ok({"asset": laptop(PRIYA)})})  # the lying system
    out = await live(tmp_path, tenant).assign_asset(101, PRIYA)
    assert (out.replayed, out.verified) == (False, False)


async def test_an_assignment_that_times_out_is_an_unknown_outcome(tmp_path):
    tenant = FakeTenant({ASSET: ok({"asset": laptop()}), PUT: httpx.ReadTimeout("slow")})
    with pytest.raises(UnknownOutcome):
        await live(tmp_path, tenant).assign_asset(101, PRIYA)


# --- FIXTURE ---------------------------------------------------------------------------------------------------

def fixture_conn(tmp_path) -> FreshserviceConnector:
    return FreshserviceConnector(None, state=FixtureState("freshservice", directory=tmp_path))


async def test_a_fixture_laptop_is_assigned_and_stays_assigned(tmp_path):
    out = await fixture_conn(tmp_path).assign_asset(101, PRIYA)
    assert (out.mode, out.verified, out.replayed) == ("FIXTURE", True, False)
    again = await fixture_conn(tmp_path).assign_asset(101, PRIYA)
    assert again.replayed and (await fixture_conn(tmp_path).get_asset(101)).data["user_id"] == PRIYA


@pytest.mark.parametrize(("display_id", "user_id", "status"), [(999, PRIYA, 404), (101, 123, 400)])
async def test_the_fixture_refuses_unknown_assets_and_people(tmp_path, display_id, user_id, status):
    with pytest.raises(ConnectorError) as e:
        await fixture_conn(tmp_path).assign_asset(display_id, user_id)
    assert e.value.status == status

"""Catalog place_request (T131): a ticket for requests that start in Slack, Teams or voice (CLAUDE.md §12).

api.freshservice.com, Create a Service Request: POST /api/v2/service_catalog/items/{display_id}/place_request
{"email", "requested_for" (email), "quantity", "custom_fields"} -> `service_request` (a ticket, type Service Request).
View Requested Items: GET /api/v2/tickets/[id]/requested_items -> `requested_items` (item form values in
`custom_fields`, the item's display id in `service_item_id`).
"""

import httpx
import pytest
from _fs_mock import API_KEY, DOMAIN, FakeTenant, ok

from contextrail.connectors.base import ConnectorError, UnknownOutcome
from contextrail.connectors.freshservice import (
    ACCESS_REQUEST_TEXT_FIELD,
    FreshserviceClient,
    FreshserviceConnector,
)
from contextrail.connectors.state import FixtureState

ITEMS = ("GET", "/api/v2/service_catalog/items")
PLACE = ("POST", "/api/v2/service_catalog/items/41/place_request")
ANIL, MEERA_MAIL = "anil.kumar@northbeam.example", "meera.iyer@northbeam.example"
CATALOG = ok({"service_items": [{"id": 9000000041, "display_id": 41, "name": "Access request (ContextRail)"}]})


def client(tenant: FakeTenant) -> FreshserviceClient:
    return FreshserviceClient(DOMAIN, API_KEY, transport=tenant.transport)


async def test_place_request_posts_the_documented_body_to_the_item_display_id():
    sr = {"id": 49, "type": "Service Request", "requester_id": 5000001042}
    tenant = FakeTenant({PLACE: ok({"service_request": sr})})
    async with client(tenant) as fs:
        got = await fs.place_request(41, email=MEERA_MAIL, requested_for=ANIL, custom_fields={"request_text": "x"})
    assert got == sr
    assert tenant.body() == {"email": MEERA_MAIL, "requested_for": ANIL, "quantity": 1,
                             "custom_fields": {"request_text": "x"}}


async def test_optional_fields_are_left_out():
    tenant = FakeTenant({PLACE: ok({"service_request": {"id": 50}})})
    async with client(tenant) as fs:
        await fs.place_request(41, email=ANIL)
    assert tenant.body() == {"email": ANIL, "quantity": 1}


async def test_an_access_request_goes_to_the_access_request_item_with_the_request_text():
    tenant = FakeTenant({ITEMS: CATALOG, PLACE: ok({"service_request": {"id": 51}})})
    async with client(tenant) as fs:
        got = await fs.place_access_request(ANIL, "Give Anil the same access as Rahul Mehta")
    assert got["id"] == 51
    assert tenant.body() == {"email": ANIL, "quantity": 1,
                             "custom_fields": {ACCESS_REQUEST_TEXT_FIELD: "Give Anil the same access as Rahul Mehta"}}


async def test_a_timed_out_request_is_an_unknown_outcome_and_is_not_resent():
    tenant = FakeTenant({ITEMS: CATALOG, PLACE: httpx.ReadTimeout("slow")})
    async with client(tenant) as fs:
        with pytest.raises(UnknownOutcome):
            await fs.place_access_request(ANIL, "Give Anil the same access as Rahul Mehta")
    assert sum(r.method == "POST" for r in tenant.requests) == 1  # a second ticket would be a duplicate request


@pytest.mark.parametrize("bad", ["", "anil", "anil kumar@northbeam.example"])
async def test_emails_are_checked_before_sending(bad):
    tenant = FakeTenant()
    async with client(tenant) as fs:
        with pytest.raises(ValueError):
            await fs.place_request(41, email=bad)
    assert tenant.requests == []


async def test_requested_items_carry_the_item_form_values():
    items = [{"id": 1, "service_item_id": 41, "custom_fields": {"request_text": "same as Rahul"}, "stage": 1}]
    tenant = FakeTenant({("GET", "/api/v2/tickets/4412/requested_items"): ok({"requested_items": items})})
    async with client(tenant) as fs:
        assert await fs.get_requested_items(4412) == items


# --- FIXTURE -------------------------------------------------------------------------------------------------

def fixture_conn(tmp_path) -> FreshserviceConnector:
    return FreshserviceConnector(None, state=FixtureState("freshservice", directory=tmp_path))


async def test_the_fixture_ticket_4412_carries_its_request_text(tmp_path):
    items = (await fixture_conn(tmp_path).get_requested_items(4412)).data
    assert items[0]["service_item_id"] == 41
    assert items[0]["custom_fields"][ACCESS_REQUEST_TEXT_FIELD] == "Give Anil the same access as Rahul"


async def test_a_fixture_access_request_becomes_a_real_fixture_ticket(tmp_path):
    conn = fixture_conn(tmp_path)
    sr = await conn.place_access_request(ANIL, "Give Anil the same access as Rahul Mehta")
    assert sr.mode == "FIXTURE" and sr.data["type"] == "Service Request"
    tid = sr.data["id"]
    ticket = (await conn.get_ticket(tid)).data
    assert ticket["requester_id"] == 5000001042 and ticket["requested_for_id"] == 5000001042
    items = (await conn.get_requested_items(tid)).data
    assert items[0]["custom_fields"][ACCESS_REQUEST_TEXT_FIELD] == "Give Anil the same access as Rahul Mehta"
    # Freshservice takes no idempotency key: a second call is a second ticket, which is why callers keep the id
    assert (await conn.place_access_request(ANIL, "again")).data["id"] == tid + 1


async def test_a_fixture_request_for_an_unknown_person_is_refused(tmp_path):
    with pytest.raises(ConnectorError) as e:
        await fixture_conn(tmp_path).place_access_request("stranger@elsewhere.example", "hello")
    assert e.value.status == 400

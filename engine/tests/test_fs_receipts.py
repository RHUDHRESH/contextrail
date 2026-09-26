"""Receipt records on a Freshservice custom object (T128, CLAUDE.md §13.2: "a custom object record (full JSON)").

api.freshservice.com, Custom Objects:
- GET  /api/v2/objects -> `custom_objects` [{id, title, ...}];  GET /api/v2/objects/[id] -> `custom_object` with fields
- POST /api/v2/objects/[id]/records {"data": {...}} -> `custom_object` {"data": {..., "bo_display_id"}}
- GET  /api/v2/objects/[id]/records?query=<field : 'value'>&page_size=n -> `records` [{"data": {...}}]
No idempotency key: every receipt carries receipt_key, looked up before posting and after.
"""

import pytest
from _fs_mock import API_KEY, DOMAIN, FakeTenant, ok

from contextrail.connectors.base import ConnectorError
from contextrail.connectors.freshservice import (
    RECEIPT_FIELDS,
    RECEIPTS_OBJECT,
    FreshserviceClient,
    FreshserviceConnector,
)
from contextrail.connectors.state import FixtureState

OBJ = 9400000001
LIST = ("GET", "/api/v2/objects")
SHOW = ("GET", f"/api/v2/objects/{OBJ}")
RECORDS_GET = ("GET", f"/api/v2/objects/{OBJ}/records")
RECORDS_POST = ("POST", f"/api/v2/objects/{OBJ}/records")
KEY = "r-9f3ae1c04b7d2a55"
RECEIPT = {"run_id": "8d1c0f3e-0000-4000-8000-000000000001", "ticket_id": 4412, "status": "partial",
           "summary": "13 verified, 2 held, 1 refused", "receipt_json": "{}", "audit_from": 1, "audit_to": 40,
           "mode": "FIXTURE"}


def objects(title: str = RECEIPTS_OBJECT, fields: tuple = RECEIPT_FIELDS):
    return {LIST: ok({"custom_objects": [{"id": 1, "title": "Service Item Approvals"}, {"id": OBJ, "title": title}]}),
            SHOW: ok({"custom_object": {"id": OBJ, "title": title,
                                        "fields": [{"name": f, "label": f, "type": "text"} for f in fields]}})}


def client(tenant: FakeTenant) -> FreshserviceClient:
    return FreshserviceClient(DOMAIN, API_KEY, transport=tenant.transport)


async def test_create_record_posts_data_and_returns_the_stored_record():
    stored = {**RECEIPT, "receipt_key": KEY, "bo_display_id": 1}
    tenant = FakeTenant({RECORDS_POST: ok({"custom_object": {"data": stored}})})
    async with client(tenant) as fs:
        assert await fs.create_record(OBJ, {**RECEIPT, "receipt_key": KEY}) == stored
    assert tenant.body() == {"data": {**RECEIPT, "receipt_key": KEY}}


async def test_find_records_sends_the_documented_query():
    tenant = FakeTenant({RECORDS_GET: ok({"records": [{"data": {"receipt_key": KEY, "bo_display_id": 3}}]})})
    async with client(tenant) as fs:
        assert await fs.find_records(OBJ, "receipt_key", KEY) == [{"receipt_key": KEY, "bo_display_id": 3}]
    params = tenant.requests[0].url.params
    assert params["query"] == f"receipt_key : '{KEY}'" and params["page_size"] == "10"


@pytest.mark.parametrize(("field", "value"), [("receipt key", KEY), ("receipt_key", "x' OR run_id : 'y"),
                                              ("receipt_key", "")])
async def test_queries_cannot_be_injected(field, value):
    tenant = FakeTenant()
    async with client(tenant) as fs:
        with pytest.raises(ValueError):
            await fs.find_records(OBJ, field, value)
    assert tenant.requests == []


async def test_the_receipts_object_is_found_by_title_and_its_fields_are_checked_once():
    tenant = FakeTenant(objects())
    async with client(tenant) as fs:
        assert (await fs.receipts_object())["id"] == OBJ
        assert (await fs.receipts_object())["id"] == OBJ
    assert len(tenant.requests) == 2  # list + show, then remembered


async def test_a_receipts_object_missing_fields_names_them_and_the_setup_task():
    tenant = FakeTenant(objects(fields=("run_id", "summary")))
    async with client(tenant) as fs:
        with pytest.raises(ConnectorError, match="receipt_key") as e:
            await fs.receipts_object()
    assert "T128" in str(e.value)


async def test_a_receipt_is_posted_once_and_confirmed_by_reading_it_back():
    stored: list[dict] = []

    def post(request):
        import json
        rec = {**json.loads(request.content)["data"], "bo_display_id": len(stored) + 1}
        stored.append(rec)
        return ok({"custom_object": {"data": rec}})

    tenant = FakeTenant({**objects(), RECORDS_POST: post,
                         RECORDS_GET: lambda r: ok({"records": [{"data": x} for x in stored
                                                                if x["receipt_key"] == KEY]})})
    async with client(tenant) as fs:
        first = await fs.add_receipt_record(RECEIPT, KEY)
        again = await fs.add_receipt_record(RECEIPT, KEY)
    assert (first.replayed, first.confirmed, first.record["bo_display_id"]) == (False, True, 1)
    assert (again.replayed, again.confirmed) == (True, True) and len(stored) == 1


async def test_a_receipt_acknowledged_but_not_readable_is_not_confirmed():
    tenant = FakeTenant({**objects(), RECORDS_POST: ok({"custom_object": {"data": {"bo_display_id": 1}}}),
                         RECORDS_GET: ok({"records": []})})
    async with client(tenant) as fs:
        out = await fs.add_receipt_record(RECEIPT, KEY)
    assert (out.replayed, out.confirmed) == (False, False)


# --- FIXTURE ---------------------------------------------------------------------------------------------------

def fixture_conn(tmp_path) -> FreshserviceConnector:
    return FreshserviceConnector(None, state=FixtureState("freshservice", directory=tmp_path))


async def test_fixture_receipts_persist_read_back_and_replay(tmp_path):
    conn = fixture_conn(tmp_path)
    first = await conn.add_receipt_record(RECEIPT, KEY)
    assert (first.mode, first.confirmed, first.replayed, first.display_id) == ("FIXTURE", True, False, 1)
    again = await fixture_conn(tmp_path).add_receipt_record(RECEIPT, KEY)
    assert (again.replayed, again.display_id) == (True, 1)


async def test_the_fixture_refuses_fields_the_object_does_not_have(tmp_path):
    with pytest.raises(ConnectorError) as e:
        await fixture_conn(tmp_path).add_receipt_record({**RECEIPT, "salary": 1}, KEY)
    assert e.value.status == 400

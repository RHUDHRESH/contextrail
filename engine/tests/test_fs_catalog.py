"""Service catalog (T125): list every item across pages and find the 'Access request (ContextRail)' item.

api.freshservice.com, View List of Service Items: GET /api/v2/service_catalog/items, envelope `service_items`,
`per_page` default 30 and max 30 for this endpoint; the `link` header carries rel="next" while more pages exist.
"""

import httpx
import pytest
from _fs_mock import API_KEY, DOMAIN, FakeTenant, ok

from contextrail.connectors.base import ConnectorError
from contextrail.connectors.freshservice import ACCESS_REQUEST_ITEM, FreshserviceClient

PATH = ("GET", "/api/v2/service_catalog/items")


def item(i: int, name: str | None = None, deleted: bool = False) -> dict:
    return {"id": 1003340000 + i, "display_id": i, "name": name or f"Item {i}", "deleted": deleted}


def paged(pages: list[list[dict]], next_url: str = "https://northbeam.freshservice.com/api/v2/x"):
    def answer(request: httpx.Request) -> httpx.Response:
        n = int(request.url.params["page"])
        more = {"link": f'<{next_url}?page={n + 1}>; rel="next"'} if n < len(pages) else {}
        return ok({"service_items": pages[n - 1]}, headers=more)
    return answer


def client(tenant: FakeTenant) -> FreshserviceClient:
    return FreshserviceClient(DOMAIN, API_KEY, transport=tenant.transport)


async def test_listing_walks_every_page_at_the_documented_page_size():
    pages = [[item(i) for i in range(1, 31)], [item(i) for i in range(31, 61)], [item(61)]]
    tenant = FakeTenant({PATH: paged(pages)})
    async with client(tenant) as fs:
        items = await fs.list_catalog_items()
    assert [i["display_id"] for i in items] == list(range(1, 62))
    assert [dict(r.url.params) for r in tenant.requests] == [
        {"page": str(n), "per_page": "30"} for n in (1, 2, 3)]


async def test_the_link_header_is_a_signal_not_a_destination():
    pages = [[item(1)], [item(2)]]
    tenant = FakeTenant({PATH: paged(pages, next_url="https://evil.example/steal")})
    async with client(tenant) as fs:
        await fs.list_catalog_items()
    assert {r.url.host for r in tenant.requests} == {DOMAIN}  # the authenticated call never follows the URL


async def test_a_tenant_that_always_says_next_is_cut_off():
    tenant = FakeTenant({PATH: lambda r: ok({"service_items": [item(int(r.url.params["page"]))]},
                                            headers={"link": '<https://x/>; rel="next"'})})
    async with client(tenant) as fs:
        items = await fs.list_catalog_items(max_pages=5)
    assert len(items) == 5 and len(tenant.requests) == 5


async def test_the_access_request_item_is_found_by_exact_name_and_remembered():
    pages = [[item(1, "Office Desktop"), item(7, "Access request (ContextRail)", deleted=True)],
             [item(41, "  access request  (contextrail) "), item(42, "Access request (ContextRail) v2")]]
    tenant = FakeTenant({PATH: paged(pages)})
    async with client(tenant) as fs:
        found = await fs.access_request_item()
        again = await fs.access_request_item()
    assert ACCESS_REQUEST_ITEM == "Access request (ContextRail)"
    assert found == {"id": 1003340041, "display_id": 41, "name": "  access request  (contextrail) "}
    assert again == found and len(tenant.requests) == 2  # second lookup served from memory


async def test_two_items_with_the_same_name_are_ambiguous_not_guessed():
    tenant = FakeTenant({PATH: paged([[item(41, ACCESS_REQUEST_ITEM), item(42, ACCESS_REQUEST_ITEM)]])})
    async with client(tenant) as fs:
        with pytest.raises(ConnectorError, match="2 catalog items"):
            await fs.access_request_item()


async def test_a_missing_item_names_the_setup_task():
    tenant = FakeTenant({PATH: paged([[item(1, "Office Desktop")]])})
    async with client(tenant) as fs:
        with pytest.raises(ConnectorError, match="T134"):
            await fs.access_request_item()
        # nothing is cached on failure: once an admin creates the item, the next call finds it
        tenant.routes[PATH] = paged([[item(41, ACCESS_REQUEST_ITEM)]])
        assert (await fs.access_request_item())["display_id"] == 41

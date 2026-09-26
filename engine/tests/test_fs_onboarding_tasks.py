"""Ticket checklist writes use Freshservice's task API and require a readback on every replay."""

import json

import httpx
import pytest
from _fs_mock import API_KEY, DOMAIN, FakeTenant, ok

from contextrail.connectors.base import ConnectorError, UnknownOutcome
from contextrail.connectors.freshservice import ONBOARDING_TASKS, FreshserviceClient, FreshserviceConnector
from contextrail.settings import Settings

PATH = "/api/v2/tickets/140/tasks"


class TicketTasks:
    def __init__(self, *, drop_posts: bool = False, timeout_after_post: bool = False) -> None:
        self.tasks: list[dict] = []
        self.drop_posts = drop_posts
        self.timeout_after_post = timeout_after_post

    def get(self, _: httpx.Request) -> httpx.Response:
        return ok({"tasks": list(self.tasks)})

    def post(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        task = {"id": len(self.tasks) + 25, "title": body["title"], "description": body["description"],
                "status": 1, "workspace_id": body.get("workspace_id")}
        if not self.drop_posts:
            self.tasks.append(task)
        if self.timeout_after_post:
            self.timeout_after_post = False
            raise httpx.ReadTimeout("response lost after task was saved")
        return ok({"task": task}, status=201)


def tenant_for(state: TicketTasks) -> FakeTenant:
    return FakeTenant({("GET", PATH): state.get, ("POST", PATH): state.post})


async def test_creates_all_six_on_live_ticket_and_replays_without_duplicate_posts():
    state = TicketTasks()
    tenant = tenant_for(state)
    settings = Settings(_env_file=None, fs_domain=DOMAIN, fs_api_key=API_KEY, fs_workspace_id=12)
    connector = FreshserviceConnector(settings, transport=tenant.transport)
    try:
        first = await connector.ensure_onboarding_tasks(140)
        second = await connector.ensure_onboarding_tasks(140)
    finally:
        await connector.aclose()

    assert [task["title"] for task in first] == [title for title, _ in ONBOARDING_TASKS]
    assert [task["id"] for task in second] == [task["id"] for task in first]
    posts = [request for request in tenant.requests if request.method == "POST"]
    assert len(posts) == 6
    assert all(json.loads(request.content)["workspace_id"] == 12 for request in posts)
    assert all("due_date" not in json.loads(request.content) for request in posts)
    assert all(task["status"] == 1 for task in first)


async def test_reconciles_a_post_that_saved_a_task_but_lost_its_response():
    state = TicketTasks(timeout_after_post=True)
    tenant = tenant_for(state)
    async with FreshserviceClient(DOMAIN, API_KEY, workspace_id=12, transport=tenant.transport) as client:
        tasks = await client.ensure_onboarding_tasks(140)
    assert len(tasks) == 6
    assert len([request for request in tenant.requests if request.method == "POST"]) == 6


async def test_an_acknowledged_task_that_cannot_be_read_back_is_not_success():
    state = TicketTasks(drop_posts=True)
    tenant = tenant_for(state)
    async with FreshserviceClient(DOMAIN, API_KEY, transport=tenant.transport) as client:
        with pytest.raises(UnknownOutcome, match="not visible on readback"):
            await client.ensure_onboarding_tasks(140)
    assert len([request for request in tenant.requests if request.method == "POST"]) == 1


async def test_a_live_403_never_writes_to_fixture():
    tenant = FakeTenant({("GET", PATH): ok({"code": "access_denied"}, status=403)})
    settings = Settings(_env_file=None, fs_domain=DOMAIN, fs_api_key=API_KEY)
    connector = FreshserviceConnector(settings, transport=tenant.transport)
    try:
        with pytest.raises(ConnectorError, match="403"):
            await connector.ensure_onboarding_tasks(140)
    finally:
        await connector.aclose()
    assert [request.method for request in tenant.requests] == ["GET"]


async def test_requires_a_live_tenant():
    connector = FreshserviceConnector(Settings(_env_file=None))
    try:
        with pytest.raises(ConnectorError, match="configured live tenant"):
            await connector.ensure_onboarding_tasks(140)
    finally:
        await connector.aclose()

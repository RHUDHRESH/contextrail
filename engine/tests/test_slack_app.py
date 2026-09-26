"""The Slack door (CLAUDE.md §13.1): Bolt wiring, HTTP route and Socket Mode entrypoint. No network: a fake Web API
client records every call, and HTTP requests are signed with a fake signing secret."""

import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_fake import BOT_TOKEN, SIGNING_SECRET, FakeSlackClient, signed_headers

from contextrail.fixtures import load
from contextrail.main import create_app
from contextrail.settings import Settings
from contextrail.surfaces import slack_socket
from contextrail.surfaces.door import Door
from contextrail.surfaces.slack_app import SlackDoor, attach

PEOPLE = {p["person_id"]: p["display_name"] for p in load("identity")["people"]}
_SLACK_ENV = ("SLACK_BOT_TOKEN", "SLACK_SIGNING_SECRET", "SLACK_APP_TOKEN")


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def _configured() -> Settings:
    return _settings(slack_bot_token=BOT_TOKEN, slack_signing_secret=SIGNING_SECRET)


@pytest.fixture
def no_slack_env(monkeypatch):
    for k in _SLACK_ENV:
        monkeypatch.delenv(k, raising=False)


@pytest.fixture
async def door(rail):
    runner, deps = rail
    modes = {n: deps.registry.get(n).mode for n in ("hris", "entitlements", "github", "slack_corpus")}
    return Door(runner, people=PEOPLE, modes=modes)


# --- T140: Bolt init, HTTP mode route, Socket Mode entrypoint ----------------------------------------------------

def test_slack_route_exists_only_when_slack_is_configured(no_slack_env):
    off = TestClient(create_app(_settings()))
    assert off.post("/slack/events", content="x").status_code == 404   # no credentials: the door is not LIVE
    on = TestClient(create_app(_configured()))
    r = on.post("/slack/events", content="x")
    assert r.status_code == 503 and "not attached" in r.json()["detail"]  # configured, but no rail wired yet


async def test_signed_requests_reach_bolt_and_forged_ones_are_refused(no_slack_env, door):
    app = create_app(_configured())
    fake = FakeSlackClient()
    slack = attach(app, door, client=fake)
    assert isinstance(slack, SlackDoor) and app.state.slack is slack
    body = json.dumps({"type": "url_verification", "challenge": "c-123", "token": "unused"})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://engine") as h:
        ok = await h.post("/slack/events", content=body, headers=signed_headers(body, content_type="application/json"))
        forged = await h.post("/slack/events", content=body,
                              headers=signed_headers(body, secret="wrong", content_type="application/json"))
        stale = await h.post("/slack/events", content=body, headers=signed_headers(
            body, timestamp=int(time.time()) - 600, content_type="application/json"))
    assert ok.status_code == 200 and ok.json()["challenge"] == "c-123"
    assert forged.status_code == 401 and stale.status_code == 401
    assert fake.calls == []  # verification needs no Slack API call


async def test_attach_refuses_when_slack_is_not_configured(no_slack_env, door):
    with pytest.raises(RuntimeError, match="SLACK_BOT_TOKEN"):
        attach(create_app(_settings()), door, client=FakeSlackClient())


async def test_socket_mode_handler_is_built_without_connecting(door):
    fake = FakeSlackClient()
    slack = SlackDoor(door, client=fake, signing_secret=SIGNING_SECRET)
    handler = slack_socket.build_handler(slack, app_token="fake-app-token")
    try:
        assert isinstance(handler, AsyncSocketModeHandler) and handler.app is slack.app
        assert fake.calls == []
    finally:
        await handler.close_async()  # releases the aiohttp session; nothing was connected


def test_socket_entrypoint_refuses_to_start_without_tokens(capsys):
    assert slack_socket.main(settings=_settings(slack_bot_token=BOT_TOKEN, slack_signing_secret=SIGNING_SECRET)) == 2
    assert "SLACK_APP_TOKEN" in capsys.readouterr().err

"""The Slack door (CLAUDE.md §13.1): Bolt wiring, HTTP route and Socket Mode entrypoint. No network: a fake Web API
client records every call, and HTTP requests are signed with a fake signing secret."""

import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_fake import BOT_TOKEN, SIGNING_SECRET, FakeSlackClient, forbid_real_slack_calls, signed_headers

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


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    forbid_real_slack_calls(monkeypatch)


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


async def test_authorization_goes_through_the_door_client_once(no_slack_env, door):
    """Bolt builds a fresh AsyncWebClient per request; auth.test must still use the door's client, and only once."""
    app = create_app(_configured())
    fake = FakeSlackClient()
    app.state.slack = SlackDoor(door, client=fake, signing_secret=SIGNING_SECRET, process_before_response=True)
    body = str(httpx.QueryParams({"command": "/not-ours", "text": "x", "user_id": "U0ANIL001", "team_id": "T0NORTH01",
                                  "channel_id": "C0ACCESS1"}))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://engine") as h:
        statuses = [(await h.post("/slack/events", content=body, headers=signed_headers(body))).status_code
                    for _ in range(2)]
    assert statuses == [404, 404]              # authorized, then no listener for this command
    assert [m for m, _ in fake.calls] == ["auth.test"]


def test_socket_entrypoint_refuses_to_start_without_tokens(capsys):
    assert slack_socket.main(settings=_settings(slack_bot_token=BOT_TOKEN, slack_signing_secret=SIGNING_SECRET)) == 2
    assert "SLACK_APP_TOKEN" in capsys.readouterr().err

# --- T141: /contextrail <request> -> ephemeral ack, then Door.start_run ------------------------------------------

ANIL_SLACK, CHANNEL = "U0ANIL001", "C0ACCESS1"
REQUEST = "Give Anil the same access as Rahul Mehta"


def _command(text: str, user: str = ANIL_SLACK) -> dict:
    return {"command": "/contextrail", "text": text, "user_id": user, "channel_id": CHANNEL, "team_id": "T0NORTH01",
            "response_url": "https://hooks.slack.invalid/commands/1", "trigger_id": "13345224609.738474920.8088930838d"}


async def _runs(door) -> list[dict]:
    async with door.db.connection() as c:
        return await (await c.execute("select * from runs order by created_at")).fetchall()


class Ack:
    """Records every ack and how many runs existed at that moment (the ack must come before the rail starts)."""

    def __init__(self, door) -> None:
        self.door, self.calls, self.runs_at_ack = door, [], []

    async def __call__(self, text: str = "", **kw) -> None:
        self.calls.append({"text": text, **kw})
        self.runs_at_ack.append(len(await _runs(self.door)))


async def test_slash_command_acks_ephemerally_then_starts_the_run(door):
    fake = FakeSlackClient()
    slack = SlackDoor(door, client=fake, signing_secret=SIGNING_SECRET)
    ack = Ack(door)
    await slack.on_command(ack=ack, command=_command(REQUEST))
    [acked] = ack.calls
    assert acked["response_type"] == "ephemeral" and REQUEST in acked["text"]
    assert ack.runs_at_ack == [0]                      # acknowledged before any run existed
    [run] = await _runs(door)
    assert (run["source"], run["requested_by"], run["status"]) == ("slack", "p-anil", "awaiting_approval")


async def test_empty_command_shows_usage_and_starts_nothing(door):
    fake = FakeSlackClient()
    slack = SlackDoor(door, client=fake, signing_secret=SIGNING_SECRET)
    ack = Ack(door)
    await slack.on_command(ack=ack, command=_command("   "))
    assert ack.calls[0]["response_type"] == "ephemeral" and "/contextrail" in ack.calls[0]["text"]
    assert await _runs(door) == [] and fake.calls == []


async def test_signed_slash_command_through_the_http_route(no_slack_env, door):
    app = create_app(_configured())
    fake = FakeSlackClient()
    app.state.slack = SlackDoor(door, client=fake, signing_secret=SIGNING_SECRET, process_before_response=True)
    body = str(httpx.QueryParams(_command(REQUEST)))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://engine") as h:
        r = await h.post("/slack/events", content=body, headers=signed_headers(body))
    assert r.status_code == 200 and r.json()["response_type"] == "ephemeral" and REQUEST in r.json()["text"]
    [run] = await _runs(door)
    assert run["requested_by"] == "p-anil"


# --- T142: one status message per run, updated in place per stage --------------------------------------------------

async def _door_messages(door, run_id) -> list[dict]:
    async with door.db.connection() as c:
        return await (await c.execute("select action_id, channel, ref from door_messages where run_id = %s",
                                      (run_id,))).fetchall()


def _text(call_args: dict) -> str:
    return json.dumps(call_args, ensure_ascii=False)


async def test_status_message_is_posted_once_then_updated_per_stage(door):
    fake = FakeSlackClient()
    slack = SlackDoor(door, client=fake, signing_secret=SIGNING_SECRET)
    await slack.on_command(ack=Ack(door), command=_command(REQUEST))
    [run] = await _runs(door)
    [posted] = fake.called("chat.postMessage")
    assert posted["channel"] == CHANNEL and REQUEST in _text(posted)
    ts = "1790000000.000001"
    assert run["source_ref"] == f"{CHANNEL}:{ts}"            # the run knows which Slack message is its status
    updates = fake.called("chat.update")
    events = door.runner.d.events.history(run["id"])
    assert len(updates) == len(events) == 9                 # discover .. finalize, one edit each, same message
    assert all((u["channel"], u["ts"]) == (CHANNEL, ts) for u in updates)
    assert "Found Anil Kumar" in _text(updates[0]) and "Step 1 of 9" in _text(updates[0])
    final = _text(updates[-1])                                 # the end of the pass renders the whole RunView
    assert "Waiting for approval" in final and "15 verified" in final and "waiting for Dana Osei" in final
    assert await _door_messages(door, run["id"]) == [{"action_id": "", "channel": "slack",
                                                      "ref": {"channel": CHANNEL, "ts": ts}}]


async def test_status_goes_to_the_requesters_dm_when_the_bot_is_not_in_the_channel(door):
    fake = FakeSlackClient(refuse_channels={CHANNEL})
    slack = SlackDoor(door, client=fake, signing_secret=SIGNING_SECRET)
    await slack.on_command(ack=Ack(door), command=_command(REQUEST))
    assert fake.called("conversations.open") == [{"users": ANIL_SLACK}]
    dm = "D" + ANIL_SLACK
    assert [p["channel"] for p in fake.called("chat.postMessage")] == [CHANNEL, dm]
    assert {u["channel"] for u in fake.called("chat.update")} == {dm}


async def test_runs_from_other_doors_do_not_touch_slack_status(door):
    fake = FakeSlackClient()
    SlackDoor(door, client=fake, signing_secret=SIGNING_SECRET)
    view = await door.start_run(REQUEST, channel="teams", actor_external_id="00000000-0000-4000-8000-000000001042")
    assert view.status == "awaiting_approval" and fake.calls == []


# --- T153: the identity map works for the Slack door, both ways ----------------------------------------------------

async def _set(door, sql: str, *params) -> None:
    async with door.db.connection() as c:
        await c.execute(sql, params)


async def test_seeded_demo_users_resolve_both_ways_without_calling_slack(door):
    fake = FakeSlackClient()
    slack = SlackDoor(door, client=fake, signing_secret=SIGNING_SECRET)
    seeded = [(p["person_id"], p["slack_user_id"]) for p in load("identity")["people"] if p["slack_user_id"]]
    assert len(seeded) >= 8 and {"p-dana", "p-meera", "p-anil"} <= {pid for pid, _ in seeded}
    for pid, sid in seeded:
        assert (await door.resolve_actor("slack", sid))["person_id"] == pid     # a click maps to the person
        assert await slack.slack_user_for(pid) == sid                          # a card finds the person
    assert fake.calls == []


async def test_email_lookup_links_an_approver_who_has_no_slack_id_yet(door):
    await _set(door, "update identity_map set slack_user_id = null where person_id = 'p-dana'")
    fake = FakeSlackClient(emails={"dana.osei@northbeam.example": "U0NEWDANA"})
    slack = SlackDoor(door, client=fake, signing_secret=SIGNING_SECRET)
    assert await slack.slack_user_for("p-dana") == "U0NEWDANA"
    assert await slack.slack_user_for("p-dana") == "U0NEWDANA"                 # linked: no second lookup
    assert fake.called("users.lookupByEmail") == [{"email": "dana.osei@northbeam.example"}]
    assert (await door.resolve_actor("slack", "U0NEWDANA"))["person_id"] == "p-dana"


async def test_no_slack_account_or_one_owned_by_someone_else_is_never_linked(door):
    await _set(door, "update identity_map set slack_user_id = null where person_id in ('p-meera', 'p-ravi')")
    fake = FakeSlackClient(emails={"meera.iyer@northbeam.example": "U0DANA050"})   # Dana's Slack account
    slack = SlackDoor(door, client=fake, signing_secret=SIGNING_SECRET)
    assert await slack.slack_user_for("p-meera") is None                       # would DM the wrong person
    assert await slack.slack_user_for("p-ravi") is None                        # users_not_found
    assert await slack.slack_user_for("p-nobody") is None                      # not in the identity map
    assert (await door.resolve_actor("slack", "U0DANA050"))["person_id"] == "p-dana"
    async with door.db.connection() as c:
        row = await (await c.execute("select slack_user_id from identity_map where person_id = 'p-meera'")).fetchone()
    assert row["slack_user_id"] is None


# --- T154 / T155: "which Rahul?" asked in the status message, answered with a button ------------------------------

AMBIGUOUS = "Give Anil the same access as Rahul"


def _pick_buttons(update: dict) -> list[dict]:
    return [e for b in update["blocks"] if b["type"] == "actions" for e in b["elements"]]


async def test_an_ambiguous_request_asks_which_one_in_the_status_message(door):
    fake = FakeSlackClient()
    slack = SlackDoor(door, client=fake, signing_secret=SIGNING_SECRET)
    await slack.on_command(ack=Ack(door), command=_command(AMBIGUOUS))
    [run] = await _runs(door)
    assert run["status"] == "needs_input"
    last = fake.called("chat.update")[-1]
    assert "Which *Rahul* do you mean?" in _text(last)
    assert [b["value"] for b in _pick_buttons(last)] == [f"{run['id']}|peer|E-0007", f"{run['id']}|peer|E-0415"]

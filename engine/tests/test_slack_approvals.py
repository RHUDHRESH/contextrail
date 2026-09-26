"""Slack approvals (CLAUDE.md §13.1): cards to the approver's DM, Approve/Refuse through Door.decide, and cards that
update themselves after a decision in any door. No network: FakeSlackClient records every Web API call."""

import json
from urllib.parse import urlencode
from uuid import UUID

import httpx
import pytest
from slack_fake import BOT_TOKEN, SIGNING_SECRET, FakeSlackClient, forbid_real_slack_calls, signed_headers

from contextrail.fixtures import load
from contextrail.main import create_app
from contextrail.settings import Settings
from contextrail.surfaces.door import Door
from contextrail.surfaces.slack_app import SlackDoor, handle_approval_dispatch, handle_door_update

PEOPLE = {p["person_id"]: p["display_name"] for p in load("identity")["people"]}
ANIL_SLACK, DANA_SLACK, MEERA_SLACK = "U0ANIL001", "U0DANA050", "U0MEER301"
REQUEST = "Give Anil the same access as Rahul Mehta"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    forbid_real_slack_calls(monkeypatch)


@pytest.fixture
def no_slack_env(monkeypatch):
    for k in ("SLACK_BOT_TOKEN", "SLACK_SIGNING_SECRET", "SLACK_APP_TOKEN"):
        monkeypatch.delenv(k, raising=False)


@pytest.fixture
async def door(rail):
    runner, deps = rail
    modes = {n: deps.registry.get(n).mode for n in ("hris", "entitlements", "github", "slack_corpus")}
    return Door(runner, people=PEOPLE, modes=modes)


@pytest.fixture
def fake():
    return FakeSlackClient()


@pytest.fixture
def slack(door, fake):
    return SlackDoor(door, client=fake, signing_secret=SIGNING_SECRET)


async def _dispatch_jobs(door) -> list[dict]:
    """The approval.dispatch jobs the rail itself enqueued (rail/approve.dispatch_holds)."""
    async with door.db.connection() as c:
        rows = await (await c.execute("select payload from jobs where kind = 'approval.dispatch' order by id")).fetchall()
    return [r["payload"] for r in rows]


async def _slack_cards(door, run_id) -> dict[str, dict]:
    async with door.db.connection() as c:
        rows = await (await c.execute("select action_id, ref from door_messages where run_id = %s "
                                      "and channel = 'slack' and action_id <> ''", (run_id,))).fetchall()
    return {r["action_id"]: r["ref"] for r in rows}


async def _anil_run(door):
    view = await door.start_run(REQUEST, channel="slack", actor_external_id=ANIL_SLACK)
    holds = {r.approver_id: r for r in view.rows if r.state == "awaiting"}
    return view, holds


def _buttons(post: dict) -> list[dict]:
    return next(b for b in post["blocks"] if b["type"] == "actions")["elements"]


# --- T147: deliver the card to the approver's DM, record it in door_messages ---------------------------------------

async def test_dispatch_jobs_deliver_cards_to_each_approvers_dm_and_record_them(door, fake, slack):
    view, holds = await _anil_run(door)
    jobs = await _dispatch_jobs(door)
    assert {j["approver"] for j in jobs} == {"p-dana", "p-meera"}
    results = [await handle_approval_dispatch(j, slack) for j in jobs]
    assert [r["status"] for r in results] == ["delivered", "delivered"]
    assert {o["users"] for o in fake.called("conversations.open")} == {DANA_SLACK, MEERA_SLACK}
    posts = {p["channel"]: p for p in fake.called("chat.postMessage")}
    assert set(posts) == {"D" + DANA_SLACK, "D" + MEERA_SLACK}
    dana_card = posts["D" + DANA_SLACK]
    h = holds["p-dana"]
    assert {b["value"] for b in _buttons(dana_card)} == {f"{view.run_id}|{h.action_id}|{h.params_hash}"}
    assert "Dana Osei" in json.dumps(dana_card, ensure_ascii=False)
    cards = await _slack_cards(door, view.run_id)
    assert cards[h.action_id] == {"channel": "D" + DANA_SLACK, "ts": "1790000000.000001", "user": DANA_SLACK}
    assert set(cards) == {holds["p-dana"].action_id, holds["p-meera"].action_id}


async def test_a_retried_dispatch_job_does_not_send_a_second_card(door, fake, slack):
    await _anil_run(door)
    job = (await _dispatch_jobs(door))[0]
    first, again = await handle_approval_dispatch(job, slack), await handle_approval_dispatch(job, slack)
    assert (first["status"], again["status"]) == ("delivered", "already_delivered")
    assert len(fake.called("chat.postMessage")) == 1


async def test_no_card_for_an_action_already_decided_elsewhere(door, fake, slack):
    view, holds = await _anil_run(door)
    h = holds["p-dana"]
    decided = await door.decide(view.run_id, h.action_id, h.params_hash, channel="teams",
                                actor_external_id="00000000-0000-4000-8000-000000000050", decision="approved")
    assert decided.outcome == "recorded"
    job = next(j for j in await _dispatch_jobs(door) if j["action_id"] == h.action_id)
    assert (await handle_approval_dispatch(job, slack))["status"] == "not_awaiting"
    assert fake.called("chat.postMessage") == []


async def test_an_approver_without_a_slack_account_gets_no_slack_card(door, fake, slack):
    async with door.db.connection() as c:
        await c.execute("update identity_map set slack_user_id = null where person_id = 'p-meera'")
    await _anil_run(door)
    job = next(j for j in await _dispatch_jobs(door) if j["approver"] == "p-meera")
    assert (await handle_approval_dispatch(job, slack))["status"] == "no_slack_user"   # email/other doors still apply
    assert fake.called("users.lookupByEmail") == [{"email": "meera.iyer@northbeam.example"}]
    assert fake.called("chat.postMessage") == []
    assert await _slack_cards(door, UUID(job["run_id"])) == {}


# --- T148: Approve / Refuse -> Door.decide --------------------------------------------------------------------------

class Ack:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, *a, **kw) -> None:
        self.calls += 1


async def _deliver(door, slack, approver: str) -> dict:
    job = next(j for j in await _dispatch_jobs(door) if j["approver"] == approver)
    return (await handle_approval_dispatch(job, slack))["ref"] | {"action_id": job["action_id"]}


def _click(fake: FakeSlackClient, ref: dict, user: str, button: str) -> tuple[dict, dict]:
    """The block_actions body Slack sends when `user` clicks `button` on the card recorded at `ref`."""
    card = next(p for p in fake.called("chat.postMessage") if p["channel"] == ref["channel"])
    action = next(b for b in _buttons(card) if b["action_id"] == button) | {"block_id": "decision"}
    body = {"type": "block_actions", "user": {"id": user}, "team": {"id": "T0NORTH01"},
            "channel": {"id": ref["channel"]}, "container": {"type": "message", "message_ts": ref["ts"],
                                                              "channel_id": ref["channel"]},
            "message": {"ts": ref["ts"]}, "actions": [action], "trigger_id": "1.2.3",
            "response_url": "https://hooks.slack.invalid/actions/1"}
    return body, action


async def _approval(door, run_id, action_id) -> dict | None:
    async with door.db.connection() as c:
        return await (await c.execute("select approver, decision, channel from approvals where run_id = %s "
                                      "and action_id = %s", (run_id, action_id))).fetchone()


async def test_approve_click_is_decided_by_the_door_and_the_run_resumes(door, fake, slack):
    view, _ = await _anil_run(door)
    ref = await _deliver(door, slack, "p-dana")
    ack = Ack()
    body, action = _click(fake, ref, DANA_SLACK, "approve")
    result = await slack.on_decision(ack=ack, body=body, action=action)
    assert ack.calls == 1 and result.outcome == "recorded"
    assert await _approval(door, view.run_id, ref["action_id"]) == {"approver": "p-dana", "decision": "approved",
                                                                    "channel": "slack"}
    row = next(r for r in (await door.get_status(view.run_id)).rows if r.action_id == ref["action_id"])
    assert row.state == "verified"                          # approved, executed and read back


async def test_refuse_click_refuses_the_action(door, fake, slack):
    view, _ = await _anil_run(door)
    ref = await _deliver(door, slack, "p-meera")
    body, action = _click(fake, ref, MEERA_SLACK, "refuse")
    assert (await slack.on_decision(ack=Ack(), body=body, action=action)).outcome == "recorded"
    assert (await _approval(door, view.run_id, ref["action_id"]))["decision"] == "refused"


async def test_a_damaged_button_value_decides_nothing(door, fake, slack):
    view, _ = await _anil_run(door)
    ref = await _deliver(door, slack, "p-dana")
    body, action = _click(fake, ref, DANA_SLACK, "approve")
    action = action | {"value": action["value"].replace("|", ";")}
    assert await slack.on_decision(ack=Ack(), body=body, action=action) is None
    assert await _approval(door, view.run_id, ref["action_id"]) is None
    [told] = fake.called("chat.postEphemeral")                                   # T149: and says so
    assert (told["user"], told["channel"]) == (DANA_SLACK, ref["channel"]) and "⛔ Not recorded" in told["text"]


# --- T149: stale cards and the wrong people are rejected by the Door, and the clicker is told why ------------------

async def _click_and_expect_rejection(door, fake, slack, ref, user, fragment) -> None:
    body, action = _click(fake, ref, user, "approve")
    result = await slack.on_decision(ack=Ack(), body=body, action=action)
    assert result.outcome == "rejected" and fragment in result.reason
    [told] = fake.called("chat.postEphemeral")
    assert (told["channel"], told["user"]) == (ref["channel"], user)        # only the clicker sees it
    assert told["text"].startswith("⛔ Not recorded") and fragment in told["text"]
    assert fake.called("chat.update") == []                                  # the card stays for the right person
    assert await _approval(door, UUID(action["value"].split("|")[0]), ref["action_id"]) is None


async def test_a_card_for_parameters_that_changed_is_rejected_and_the_clicker_is_told(door, fake, slack):
    view, _ = await _anil_run(door)
    ref = await _deliver(door, slack, "p-dana")
    async with door.db.connection() as c:    # the action's parameters change after the card went out
        await c.execute("update actions set params_hash = %s where run_id = %s and id = %s",
                        ("e" * 64, view.run_id, ref["action_id"]))
    await _click_and_expect_rejection(door, fake, slack, ref, DANA_SLACK, "out of date")


async def test_someone_who_is_not_the_named_approver_is_rejected_and_told(door, fake, slack):
    await _anil_run(door)
    ref = await _deliver(door, slack, "p-dana")
    await _click_and_expect_rejection(door, fake, slack, ref, "U0RAHU007", "only Dana Osei can decide this")


async def test_a_slack_user_outside_the_identity_map_is_rejected_and_told(door, fake, slack):
    await _anil_run(door)
    ref = await _deliver(door, slack, "p-dana")
    await _click_and_expect_rejection(door, fake, slack, ref, "U0STRANGER", "unknown identity")


# --- T150: the card updates itself after a decision, in whichever door it was made -------------------------------

DANA_TEAMS = "00000000-0000-4000-8000-000000000050"


async def _door_update_jobs(door) -> list[dict]:
    async with door.db.connection() as c:
        rows = await (await c.execute("select payload from jobs where kind = 'door.update' order by id")).fetchall()
    return [r["payload"] for r in rows]


def _is_decided(update: dict, ref: dict, fragment: str) -> bool:
    shown = json.dumps(update, ensure_ascii=False)
    return ((update["channel"], update["ts"]) == (ref["channel"], ref["ts"]) and fragment in shown
            and '"actions"' not in shown)


async def test_a_slack_decision_updates_the_card_in_place(door, fake, slack):
    await _anil_run(door)
    ref = await _deliver(door, slack, "p-dana")
    body, action = _click(fake, ref, DANA_SLACK, "approve")
    await slack.on_decision(ack=Ack(), body=body, action=action)
    [update] = fake.called("chat.update")
    assert _is_decided(update, ref, "✅ *Approved* by Dana Osei in Slack")


async def test_a_decision_in_teams_updates_the_slack_card_through_the_door_update_job(door, fake, slack):
    view, holds = await _anil_run(door)
    ref = await _deliver(door, slack, "p-dana")
    h = holds["p-dana"]
    decided = await door.decide(view.run_id, h.action_id, h.params_hash, channel="teams",
                                actor_external_id=DANA_TEAMS, decision="approved")
    assert decided.outcome == "recorded" and fake.called("chat.update") == []
    [job] = await _door_update_jobs(door)                        # queued by Door.decide itself
    assert (await handle_door_update(job, slack))["status"] == "updated"
    [update] = fake.called("chat.update")
    assert _is_decided(update, ref, "✅ *Approved* by Dana Osei in Teams")


async def test_a_late_slack_click_learns_who_decided_first(door, fake, slack):
    view, holds = await _anil_run(door)
    ref = await _deliver(door, slack, "p-dana")
    h = holds["p-dana"]
    await door.decide(view.run_id, h.action_id, h.params_hash, channel="teams", actor_external_id=DANA_TEAMS,
                      decision="approved")
    body, action = _click(fake, ref, DANA_SLACK, "refuse")
    assert (await slack.on_decision(ack=Ack(), body=body, action=action)).outcome == "already_decided"
    [update] = fake.called("chat.update")
    assert _is_decided(update, ref, "Approved* by Dana Osei in Teams")        # first decision wins, shown


async def test_door_update_for_an_action_with_no_slack_card_does_nothing(door, fake, slack):
    view, holds = await _anil_run(door)
    h = holds["p-meera"]
    await door.decide(view.run_id, h.action_id, h.params_hash, channel="email",
                      actor_external_id="meera.iyer@northbeam.example", decision="approved")
    [job] = await _door_update_jobs(door)
    assert (await handle_door_update(job, slack))["status"] == "no_card"
    assert fake.called("chat.update") == []


async def test_signed_button_click_through_the_http_route(no_slack_env, door, fake):
    app = create_app(Settings(_env_file=None, slack_bot_token=BOT_TOKEN, slack_signing_secret=SIGNING_SECRET))
    slack = app.state.slack = SlackDoor(door, client=fake, signing_secret=SIGNING_SECRET, process_before_response=True)
    view, _ = await _anil_run(door)
    ref = await _deliver(door, slack, "p-dana")
    body, _ = _click(fake, ref, DANA_SLACK, "approve")
    form = urlencode({"payload": json.dumps(body)})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://engine") as h:
        r = await h.post("/slack/events", content=form, headers=signed_headers(form))
    assert r.status_code == 200
    assert (await _approval(door, view.run_id, ref["action_id"]))["channel"] == "slack"

"""Slack approvals (CLAUDE.md §13.1): cards to the approver's DM, Approve/Refuse through Door.decide, and cards that
update themselves after a decision in any door. No network: FakeSlackClient records every Web API call."""

import json
from uuid import UUID

import pytest
from slack_fake import SIGNING_SECRET, FakeSlackClient, forbid_real_slack_calls

from contextrail.fixtures import load
from contextrail.surfaces.door import Door
from contextrail.surfaces.slack_app import SlackDoor, handle_approval_dispatch

PEOPLE = {p["person_id"]: p["display_name"] for p in load("identity")["people"]}
ANIL_SLACK, DANA_SLACK, MEERA_SLACK = "U0ANIL001", "U0DANA050", "U0MEER301"
REQUEST = "Give Anil the same access as Rahul Mehta"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    forbid_real_slack_calls(monkeypatch)


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

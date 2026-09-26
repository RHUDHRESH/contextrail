"""The email door end to end (CLAUDE.md §13.6, P0-10, checklist T233): the approval email's link is the only way an
email decides, and it decides through door.decide, so identity, params_hash, separation of duties, first-decision-
wins, the Freshservice mirror and every other door's update all apply exactly as they do for Slack and Teams."""

import email
import email.policy
import re
from pathlib import Path

import httpx
import psycopg
import pytest

from contextrail.connectors.ses import SesConnector
from contextrail.fixtures import load
from contextrail.main import create_app
from contextrail.settings import Settings
from contextrail.surfaces.decision_link import LinkSigner
from contextrail.surfaces.door import Door
from contextrail.surfaces.email import EmailDoorContext, handle_approval_dispatch_email

SECRET = "test-only-decision-link-secret-0123456789abcdef"  # obviously fake
PEOPLE = {p["person_id"]: p["display_name"] for p in load("identity")["people"]}
DANA_TEAMS, MEERA_SLACK = "00000000-0000-4000-8000-000000000050", "U0MEER301"


@pytest.fixture
async def flow(rail, tmp_path):
    runner, deps = rail
    modes = {n: deps.registry.get(n).mode for n in ("hris", "entitlements", "github", "slack_corpus")}
    door = Door(runner, people=PEOPLE, modes=modes)
    view = await door.start_run("Give Anil the same access as Rahul Mehta", channel="slack",
                                actor_external_id="U0ANIL001")
    ctx = EmailDoorContext(door=door, ses=SesConnector(Settings(_env_file=None, ses_from_address=""),
                                                       outbox_dir=tmp_path),
                           signer=LinkSigner(SECRET), public_url="https://cr.test")
    async with deps.db.connection() as c:
        (payload,) = [j["payload"] for j in await (await c.execute(
            "select payload from jobs where kind = 'approval.dispatch'")).fetchall() if j["payload"]["approver"] == "p-meera"]
    sent = await handle_approval_dispatch_email(payload, ctx)
    body = email.message_from_bytes(Path(sent.outbox_path).read_bytes(), policy=email.policy.default)
    approve, refuse = re.findall(r"^https://cr\.test(/a/\S+)$", body.get_body(("plain",)).get_content(), re.MULTILINE)
    app = create_app(Settings(_env_file=None, decision_link_secret=SECRET, public_url="https://cr.test"))
    app.state.door = door
    row = next(r for r in view.rows if r.approver_id == "p-meera")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://cr.test") as http:
        yield {"http": http, "door": door, "deps": deps, "view": view, "row": row, "approve": approve,
               "refuse": refuse}


async def q(deps, sql, *params) -> list[dict]:
    async with deps.db.connection() as c:
        return await (await c.execute(sql, params)).fetchall()


async def test_meera_approves_from_her_email_and_every_consequence_follows(flow):
    http, deps, view, row = flow["http"], flow["deps"], flow["view"], flow["row"]
    assert (await http.get(flow["approve"])).status_code == 200            # the link opens a confirm page
    assert await q(deps, "select * from approvals") == []                  # ...which decided nothing
    r = await http.post(flow["approve"], data={"reason": "manager ok"})
    assert r.status_code == 200 and "Approved" in r.text
    (a,) = await q(deps, "select * from approvals")
    assert (a["run_id"], a["action_id"], a["approver"], a["channel"], a["decision"], a["params_hash"]) == (
        view.run_id, row.action_id, "p-meera", "email", "approved", row.params_hash)
    (ev,) = await q(deps, "select payload from audit where event = 'approval.decided'")
    assert ev["payload"]["channel"] == "email" and ev["payload"]["approver"] == "p-meera"
    jobs = {j["kind"]: j["payload"] for j in await q(deps, "select kind, payload from jobs")}
    assert jobs["fs.approval.mirror"] == {"run_id": str(view.run_id), "action_id": row.action_id}  # -> Freshservice
    assert jobs["door.update"] == {"run_id": str(view.run_id), "action_id": row.action_id,          # -> other doors
                                   "decided_by": "p-meera", "channel": "email"}
    now = await flow["door"].get_status(view.run_id)
    assert next(x for x in now.rows if x.action_id == row.action_id).state == "verified"   # the run resumed
    assert now.status == "awaiting_approval"                                              # Dana still to decide


async def test_the_run_completes_when_the_other_approver_decides_in_teams(flow):
    http, door, view = flow["http"], flow["door"], flow["view"]
    assert (await http.post(flow["approve"])).status_code == 200
    dana = next(r for r in view.rows if r.approver_id == "p-dana")
    r = await door.decide(view.run_id, dana.action_id, dana.params_hash, channel="teams",
                          actor_external_id=DANA_TEAMS, decision="approved")
    assert r.outcome == "recorded" and r.view.status == "partial"   # partial: the refusal stands (P4)
    assert r.view.counts["verified"] == 17 and r.view.counts["refuse"] == 1


async def test_a_decision_in_another_door_wins_and_the_email_link_is_told_who(flow):
    http, door, deps, view, row = flow["http"], flow["door"], flow["deps"], flow["view"], flow["row"]
    first = await door.decide(view.run_id, row.action_id, row.params_hash, channel="slack",
                              actor_external_id=MEERA_SLACK, decision="refused", reason="no budget")
    assert first.outcome == "recorded"
    jobs_before = len(await q(deps, "select id from jobs"))
    page = await http.get(flow["approve"])
    assert page.status_code == 409 and "already refused by Meera Iyer via slack" in page.text
    r = await http.post(flow["approve"])
    assert r.status_code == 409 and "already refused by Meera Iyer via slack" in r.text
    (a,) = await q(deps, "select channel, decision from approvals")
    assert a == {"channel": "slack", "decision": "refused"}
    assert len(await q(deps, "select id from jobs")) == jobs_before   # no second mirror, no second door update


async def test_refusing_from_email_is_final(flow):
    http, door, view, row = flow["http"], flow["door"], flow["view"], flow["row"]
    r = await http.post(flow["refuse"])
    assert r.status_code == 200 and "Refused" in r.text
    assert next(x for x in (await door.get_status(view.run_id)).rows if x.action_id == row.action_id).state == "refused"
    assert (await http.post(flow["approve"])).status_code == 409   # the other button cannot overturn it


async def test_separation_of_duties_applies_to_email_links(flow, migrated_db):
    http, deps, view = flow["http"], flow["deps"], flow["view"]
    with psycopg.connect(migrated_db, autocommit=True) as c:   # suppose Meera turns out to be the requester
        c.execute("update runs set requested_by = 'p-meera' where id = %s", (view.run_id,))
    r = await http.post(flow["approve"])
    assert r.status_code == 403 and "void" in r.text
    assert await q(deps, "select * from approvals") == []
    (ev,) = await q(deps, "select payload from audit where event = 'approval.rejected'")
    assert (ev["payload"]["rule_id"], ev["payload"]["channel"]) == ("POL-SOD-001", "email")


async def test_an_approver_removed_from_the_identity_map_cannot_use_an_old_link(flow, migrated_db):
    http, deps = flow["http"], flow["deps"]
    with psycopg.connect(migrated_db, autocommit=True) as c:
        c.execute("delete from identity_map where person_id = 'p-meera'")
    r = await http.post(flow["approve"])
    assert r.status_code == 403 and "unknown identity" in r.text
    assert await q(deps, "select * from approvals") == []
    (ev,) = await q(deps, "select payload from audit where event = 'approval.rejected'")
    assert ev["payload"]["channel"] == "email"

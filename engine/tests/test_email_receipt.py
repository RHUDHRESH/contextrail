"""Receipt email to the requester on finalize (CLAUDE.md §13.6, checklist T235): once the run reaches its final
outcome, the requester gets one email built from RunView, with every row's lamp and state, refusals with their
clause, the honest modes and the audit seq range the receipt covers."""

import email
import email.policy
from pathlib import Path

import pytest

from contextrail.connectors.ses import SesConnector
from contextrail.fixtures import load
from contextrail.rail.email_intake import InboundEmail
from contextrail.settings import Settings
from contextrail.surfaces.decision_link import LinkSigner
from contextrail.surfaces.door import Door
from contextrail.surfaces.email import EmailDoorContext, handle_inbound_email, handle_receipt_email

SECRET = "test-only-decision-link-secret-0123456789abcdef"  # obviously fake
PEOPLE = {p["person_id"]: p["display_name"] for p in load("identity")["people"]}
DANA_TEAMS, MEERA_SLACK = "00000000-0000-4000-8000-000000000050", "U0MEER301"


@pytest.fixture
async def env(rail, tmp_path):
    runner, deps = rail
    modes = {n: deps.registry.get(n).mode for n in ("hris", "entitlements", "github", "slack_corpus")}
    door = Door(runner, people=PEOPLE, modes=modes)
    ctx = EmailDoorContext(door=door, ses=SesConnector(Settings(_env_file=None, ses_from_address=""),
                                                       outbox_dir=tmp_path),
                           signer=LinkSigner(SECRET), public_url="https://cr.test")
    return ctx, deps, tmp_path


async def finish(door, view):
    for approver, channel, actor in (("p-dana", "teams", DANA_TEAMS), ("p-meera", "slack", MEERA_SLACK)):
        row = next(r for r in view.rows if r.approver_id == approver)
        r = await door.decide(view.run_id, row.action_id, row.params_hash, channel=channel, actor_external_id=actor,
                              decision="approved")
        assert r.outcome == "recorded"
    return await door.get_status(view.run_id)


async def receipt_jobs(deps, run_id) -> dict:
    async with deps.db.connection() as c:
        rows = await (await c.execute("select payload from jobs where kind = 'receipt.build' and payload->>'run_id' = %s",
                                      (str(run_id),))).fetchall()
    return {r["payload"]["status"]: r["payload"] for r in rows}


def body(path: str) -> str:
    msg = email.message_from_bytes(Path(path).read_bytes(), policy=email.policy.default)
    return msg["To"], msg["Subject"], msg.get_body(("plain",)).get_content(), msg.get_body(("html",)).get_content()


async def email_run(ctx):
    out = await handle_inbound_email(ctx.door, InboundEmail(
        sender="anil.kumar@northbeam.example", subject="Access", ticket_id="4711",
        body="Give Anil the same access as Rahul Mehta"))
    return out.run


async def test_the_requester_gets_a_receipt_when_the_run_is_final(env):
    ctx, deps, _ = env
    view = await finish(ctx.door, await email_run(ctx))
    assert view.status == "partial"
    out = await handle_receipt_email((await receipt_jobs(deps, view.run_id))["partial"], ctx)
    assert (out.outcome, out.mode) == ("sent", "FIXTURE")
    to, subject, text, html = body(out.outbox_path)
    assert to == "anil.kumar@northbeam.example" and subject.startswith("Receipt · ")
    flat = " ".join(text.split())
    refused = next(r for r in view.rows if r.verdict == "REFUSE")
    for needle in ("✅ 17 done and verified", "⛔ 1 refused", "AWS payments-prod AdministratorAccess",
                   "Rule: POL-ACC-003", " ".join(refused.clause.split()), "Mode: entitlements FIXTURE"):
        assert needle in flat, needle
    async with deps.db.connection() as c:   # the receipt covers every row written before it was built
        seqs = await (await c.execute(
            "select min(seq) as lo, max(seq) as hi from audit where run_id = %s and event <> 'receipt.email_sent'",
            (view.run_id,))).fetchone()
        (sent,) = await (await c.execute("select payload from audit where event = 'receipt.email_sent'")).fetchall()
    assert f"Audit: seq {seqs['lo']} to {seqs['hi']}" in flat
    assert (sent["payload"]["audit_from"], sent["payload"]["audit_to"]) == (seqs["lo"], seqs["hi"])
    assert "AWS payments-prod AdministratorAccess" in html and "POL-ACC-003" in html


async def test_no_receipt_while_the_run_still_waits(env):
    ctx, deps, outbox = env
    view = await email_run(ctx)
    out = await handle_receipt_email((await receipt_jobs(deps, view.run_id))["awaiting_approval"], ctx)
    assert out.outcome == "skipped" and "awaiting_approval" in out.reason and list(outbox.glob("*.eml")) == []


async def test_one_receipt_per_run(env):
    ctx, deps, outbox = env
    view = await finish(ctx.door, await email_run(ctx))
    job = (await receipt_jobs(deps, view.run_id))["partial"]
    await handle_receipt_email(job, ctx)
    again = await handle_receipt_email(job, ctx)
    assert again.outcome == "replayed" and len(list(outbox.glob("*.eml"))) == 1


async def test_a_slack_request_from_someone_who_prefers_slack_gets_no_email(env):
    ctx, deps, outbox = env
    view = await ctx.door.start_run("Give Anil the same access as Rahul Mehta", channel="slack",
                                    actor_external_id="U0ANIL001")
    view = await finish(ctx.door, view)
    out = await handle_receipt_email((await receipt_jobs(deps, view.run_id))["partial"], ctx)
    assert out.outcome == "skipped" and "slack" in out.reason and list(outbox.glob("*.eml")) == []

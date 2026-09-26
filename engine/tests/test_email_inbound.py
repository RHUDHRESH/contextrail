"""Inbound email routing (CLAUDE.md §13.6, T229): request -> a run, query -> an answer, approval-reply -> no decision."""

import pytest

from contextrail.fixtures import load
from contextrail.rail.email_intake import InboundEmail
from contextrail.surfaces.door import Door
from contextrail.surfaces.email import handle_inbound_email

PEOPLE = {p["person_id"]: p["display_name"] for p in load("identity")["people"]}
ANIL_EMAIL, MEERA_EMAIL = "anil.kumar@northbeam.example", "meera.iyer@northbeam.example"


@pytest.fixture
def door(rail):
    runner, deps = rail
    return Door(runner, people=PEOPLE, modes={n: deps.registry.get(n).mode for n in ("hris", "entitlements")}), deps


async def _count(deps, table):
    async with deps.db.connection() as c:
        return (await (await c.execute(f"select count(*) as n from {table}")).fetchone())["n"]


async def test_a_request_email_starts_a_run_for_the_mapped_sender(door):
    d, deps = door
    out = await handle_inbound_email(d, InboundEmail(
        sender=ANIL_EMAIL, subject="Access", ticket_id="4711",
        body="Give Anil the same access as Rahul Mehta\n\n-- \nAnil"))
    assert (out.kind, out.intent) == ("request", "access.same_as_peer")
    assert (out.run.source, out.run.status, out.run.request_text) == (
        "email", "awaiting_approval", "Give Anil the same access as Rahul Mehta")   # signature not kept
    async with deps.db.connection() as c:
        run = await (await c.execute("select source_ref, requested_by from runs where id = %s",
                                     (out.run.run_id,))).fetchone()
    assert run == {"source_ref": "4711", "requested_by": "p-anil"}


async def test_a_query_email_is_answered_and_starts_nothing(door):
    d, deps = door
    await handle_inbound_email(d, InboundEmail(sender=ANIL_EMAIL, subject="Access", ticket_id="4711",
                                               body="Give Anil the same access as Rahul Mehta"))
    runs = await _count(deps, "runs")
    out = await handle_inbound_email(d, InboundEmail(
        sender=ANIL_EMAIL, subject="Re: Access", ticket_id="4712",
        body="Any update on my access request?\n\nOn Mon, 28 Sep 2026, ContextRail wrote:\n> Give Anil the same "
             "access as Rahul Mehta"))
    assert out.kind == "query" and out.run is None
    assert "15 done and verified" in out.answer.text and out.answer.citations
    assert await _count(deps, "runs") == runs


async def test_an_emailed_approve_is_never_a_decision(door):
    d, deps = door
    await handle_inbound_email(d, InboundEmail(sender=ANIL_EMAIL, subject="Access", ticket_id="4711",
                                               body="Give Anil the same access as Rahul Mehta"))
    before = (await _count(deps, "runs"), await _count(deps, "approvals"))
    out = await handle_inbound_email(d, InboundEmail(sender=MEERA_EMAIL, subject="Re: Approval needed",
                                                     ticket_id="4711", body="Approved"))
    assert out.kind == "approval_reply" and out.run is None and out.answer is None
    assert "Approve" in out.note and "button" in out.note
    assert (await _count(deps, "runs"), await _count(deps, "approvals")) == before

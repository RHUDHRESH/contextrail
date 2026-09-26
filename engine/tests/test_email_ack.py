"""Requester acknowledgement (CLAUDE.md §13.6, checklist T234): a request that arrived by email is answered with a
Freshservice ticket reply, so the thread stays in the requester's inbox and on the ticket. Rendered from RunView,
sent once per run. The LIVE reply endpoint belongs to the Freshservice connector; here a fake stands in."""

import pytest

from contextrail.connectors.base import ConnectorError
from contextrail.fixtures import load
from contextrail.rail.email_intake import InboundEmail
from contextrail.surfaces.door import Door
from contextrail.surfaces.email import handle_inbound_email, render_requester_ack, send_requester_ack

PEOPLE = {p["person_id"]: p["display_name"] for p in load("identity")["people"]}
ANIL = "anil.kumar@northbeam.example"


class FakeReplier:
    """Stands in for the Freshservice connector's ticket reply (POST /api/v2/tickets/{id}/reply, not yet LIVE)."""

    mode = "FIXTURE"

    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.fail = fail

    async def reply(self, ticket_id: str, body_html: str, *, idempotency_key: str) -> dict:
        if self.fail:
            raise ConnectorError("freshservice: 503")
        self.calls.append((ticket_id, body_html, idempotency_key))
        return {"id": 9000 + len(self.calls)}


@pytest.fixture
def door(rail):
    runner, deps = rail
    modes = {n: deps.registry.get(n).mode for n in ("hris", "entitlements", "github", "slack_corpus")}
    return Door(runner, people=PEOPLE, modes=modes), deps


def request(body="Give Anil the same access as Rahul Mehta", ticket_id="4711"):
    return InboundEmail(sender=ANIL, subject="Access", body=body, ticket_id=ticket_id)


async def test_a_request_email_is_acknowledged_on_its_ticket(door):
    d, _ = door
    replier = FakeReplier()
    out = await handle_inbound_email(d, request(), replier=replier)
    assert (out.ack.outcome, out.ack.mode, out.ack.reply_id) == ("sent", "FIXTURE", "9001")
    ((ticket, body, _),) = replier.calls
    assert ticket == "4711"
    for needle in ("Give Anil the same access as Rahul Mehta", "15 done and verified",
                   "2 waiting for approval: Dana Osei, Meera Iyer",
                   "1 refused: AWS payments-prod AdministratorAccess (POL-ACC-003)", "FIXTURE"):
        assert needle in body, needle


async def test_the_acknowledgement_goes_once_per_run(door):
    d, _ = door
    replier = FakeReplier()
    out = await handle_inbound_email(d, request(), replier=replier)
    again = await send_requester_ack(d, replier, out.run, ticket_id="4711")
    assert again.outcome == "replayed" and len(replier.calls) == 1


async def test_a_request_that_needs_input_asks_the_question(door):
    d, _ = door
    replier = FakeReplier()
    out = await handle_inbound_email(d, request("Give Anil the same access as Rahul"), replier=replier)
    assert out.run.status == "needs_input"
    body = replier.calls[0][1]
    assert "Which Rahul" in body and "Rahul Mehta (payments)" in body and "Rahul Verma (risk-analytics)" in body


async def test_an_emailed_approve_gets_no_reply(door):
    d, _ = door
    replier = FakeReplier()
    out = await handle_inbound_email(d, InboundEmail(sender="meera.iyer@northbeam.example",
                                                     subject="Re: Approval needed", body="Approved",
                                                     ticket_id="4713"), replier=replier)
    assert out.ack is None and out.reply is None and replier.calls == []


async def test_a_question_is_answered_not_acknowledged(door):
    d, _ = door
    replier = FakeReplier()
    out = await handle_inbound_email(d, InboundEmail(sender=ANIL, subject="Re: Access", ticket_id="4712",
                                                     body="Any update on my access request?"), replier=replier)
    assert out.ack is None and out.reply.outcome == "sent" and "We received your request" not in replier.calls[0][1]


async def test_no_ticket_means_no_reply(door):
    d, _ = door
    replier = FakeReplier()
    out = await handle_inbound_email(d, request(ticket_id=None), replier=replier)
    assert out.ack.outcome == "skipped" and replier.calls == []


async def test_a_failed_reply_leaves_the_run_alone_and_can_be_retried(door):
    d, deps = door
    out = await handle_inbound_email(d, request(), replier=FakeReplier(fail=True))
    assert out.run.status == "awaiting_approval" and out.ack.outcome == "failed" and "503" in out.ack.reason
    async with deps.db.connection() as c:
        assert await (await c.execute("select * from door_messages where channel = 'freshservice'")).fetchall() == []
    retry = await send_requester_ack(d, FakeReplier(), out.run, ticket_id="4711")
    assert retry.outcome == "sent"


async def test_the_requesters_words_are_escaped(door):
    d, _ = door
    out = await handle_inbound_email(d, request(), replier=FakeReplier())
    view = out.run.model_copy(update={"request_text": "<img src=x onerror=alert(1)> please"})
    body = render_requester_ack(view)
    assert "<img" not in body and "&lt;img" in body

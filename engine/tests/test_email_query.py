"""Status/query emails (CLAUDE.md §13.6, §13.0, checklist T236): answered only from stored facts through
door.answer_query, replied on the requester's ticket, citing the audit seq numbers the answer is drawn from."""

import pytest

from contextrail.fixtures import load
from contextrail.rail.email_intake import InboundEmail
from contextrail.surfaces.door import Door
from contextrail.surfaces.email import handle_inbound_email

PEOPLE = {p["person_id"]: p["display_name"] for p in load("identity")["people"]}
ANIL = "anil.kumar@northbeam.example"
QUESTION = InboundEmail(sender=ANIL, subject="Re: Access", ticket_id="4712",
                        body="Any update on my access request?\n\nOn Mon, ContextRail wrote:\n> We received it")


class FakeReplier:
    mode = "FIXTURE"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def reply(self, ticket_id: str, body_html: str, *, idempotency_key: str) -> dict:
        self.calls.append((ticket_id, body_html))
        return {"id": 7000 + len(self.calls)}


@pytest.fixture
def door(rail):
    runner, deps = rail
    modes = {n: deps.registry.get(n).mode for n in ("hris", "entitlements", "github", "slack_corpus")}
    return Door(runner, people=PEOPLE, modes=modes), deps


async def test_a_status_question_is_answered_on_its_ticket_with_audit_citations(door):
    d, deps = door
    first = await handle_inbound_email(d, InboundEmail(sender=ANIL, subject="Access", ticket_id="4711",
                                                       body="Give Anil the same access as Rahul Mehta"))
    replier = FakeReplier()
    out = await handle_inbound_email(d, QUESTION, replier=replier)
    assert out.kind == "query" and out.reply.outcome == "sent" and out.answer.run_id == first.run.run_id
    ((ticket, body),) = replier.calls
    assert ticket == "4712"
    assert "15 done and verified" in body and "Dana Osei" in body and "Meera Iyer" in body
    async with deps.db.connection() as c:
        rows = await (await c.execute("select seq, event from audit where run_id = %s and seq = any(%s)",
                                      (first.run.run_id, out.answer.citations))).fetchall()
    assert out.answer.citations and {r["event"] for r in rows} <= {"stage.finalize", "approval.decided"}
    assert len(rows) == len(out.answer.citations)                     # every citation is a real row of this run
    assert "Sources: audit seq " + ", ".join(map(str, out.answer.citations)) in body


async def test_a_retried_question_is_answered_once(door):
    d, _ = door
    await handle_inbound_email(d, InboundEmail(sender=ANIL, subject="Access", ticket_id="4711",
                                               body="Give Anil the same access as Rahul Mehta"))
    replier = FakeReplier()
    await handle_inbound_email(d, QUESTION, replier=replier)
    again = await handle_inbound_email(d, QUESTION, replier=replier)
    assert again.reply.outcome == "replayed" and len(replier.calls) == 1


async def test_someone_with_no_request_is_told_so_without_citations(door):
    d, _ = door
    replier = FakeReplier()
    out = await handle_inbound_email(d, InboundEmail(sender="stranger@elsewhere.example", subject="?",
                                                     ticket_id="4799", body="What is the status of my request?"),
                                     replier=replier)
    assert out.reply.outcome == "sent" and out.answer.citations == []
    assert "can't find a request from you" in replier.calls[0][1] and "Sources:" not in replier.calls[0][1]

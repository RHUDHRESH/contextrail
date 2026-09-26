"""The Email door (CLAUDE.md §13.6, D-007). Thin: it classifies, then calls the door contract, and decides nothing.

Inbound email arrives as a Freshservice ticket. `handle_inbound_email` routes it by what Discover says it is:
- a request starts a run, attributed to the sender through the identity map;
- a query is answered from stored facts (door.answer_query), and starts nothing;
- an approval-reply ("Approved") is never a decision. A From header can be forged and the body is untrusted text,
  so decisions arrive only through the signed Approve/Refuse links (/a/{token}), which go through door.decide.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from contextrail.logs import get_logger
from contextrail.rail.discover import IntentExtractor, RequestKind
from contextrail.rail.email_intake import InboundEmail, classify_email
from contextrail.surfaces.door import Answer, Door
from contextrail.surfaces.presenter import RunView

log = get_logger("contextrail.email")

APPROVAL_REPLY_NOTE = ("Replies are not decisions. To decide, open the approval email and press its Approve or "
                       "Refuse button; you will be asked to confirm on the page it opens.")


class InboundOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: RequestKind
    intent: str
    extractor: str
    run: RunView | None = None
    answer: Answer | None = None
    note: str | None = None


async def handle_inbound_email(door: Door, email: InboundEmail, *,
                               extractor: IntentExtractor | None = None) -> InboundOutcome:
    intent = await classify_email(email, extractor or door.runner.d.extractor)
    base = {"kind": intent.kind, "intent": intent.intent, "extractor": intent.extractor}
    if intent.kind == "approval_reply":
        log.info("email_approval_reply_ignored", ticket_id=email.ticket_id)
        return InboundOutcome(**base, note=APPROVAL_REPLY_NOTE)
    if intent.kind == "query":
        answer = await door.answer_query(email.text, channel="email", actor_external_id=email.sender)
        return InboundOutcome(**base, answer=answer)
    view = await door.start_run(email.text, channel="email", actor_external_id=email.sender,
                                source_ref=email.ticket_id)
    return InboundOutcome(**base, run=view)

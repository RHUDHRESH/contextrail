"""The Email door (CLAUDE.md §13.6, D-007). Thin: it classifies, renders, sends, and decides nothing.

Inbound email arrives as a Freshservice ticket. `handle_inbound_email` routes it by what Discover says it is:
- a request starts a run, attributed to the sender through the identity map;
- a query is answered from stored facts (door.answer_query), and starts nothing;
- an approval-reply ("Approved") is never a decision. A From header can be forged and the body is untrusted text,
  so decisions arrive only through the signed Approve/Refuse links (/a/{token}), which go through door.decide.

Outbound, `handle_approval_dispatch_email` handles an `approval.dispatch` job for an approver whose preferred door is
email: it renders the approval email from RunView/RowView (the same view every door renders, so they cannot
disagree), signs one Approve and one Refuse link, and sends through SES once per (run, action).
"""

from __future__ import annotations

import html
import textwrap
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from contextrail.audit import chain
from contextrail.canonical import sha256_hex
from contextrail.connectors.base import ConnectorError
from contextrail.connectors.once import send_once
from contextrail.connectors.ses import OutboundEmail, SesConnector
from contextrail.logs import get_logger
from contextrail.rail.discover import IntentExtractor, RequestKind
from contextrail.rail.email_intake import InboundEmail, classify_email
from contextrail.surfaces.decision_link import LinkClaims, LinkSigner, format_ist
from contextrail.surfaces.door import Answer, Door
from contextrail.surfaces.presenter import RowView, RunView

log = get_logger("contextrail.email")

APPROVAL_REPLY_NOTE = ("Replies are not decisions. To decide, open the approval email and press its Approve or "
                       "Refuse button; you will be asked to confirm on the page it opens.")
PHONE_WIDTH = 64  # plain-text lines stay short enough for a phone screen without sideways scrolling


# --- inbound ------------------------------------------------------------------------------------------------

class TicketReplier(Protocol):
    """A public reply on a Freshservice ticket, which Freshservice emails to the requester in the same thread.

    The LIVE implementation belongs to the Freshservice connector: `POST /api/v2/tickets/{id}/reply` with
    `{"body": "<html>"}`, answering 201 `{"conversation": {"id": ...}}`, as used by the pinned refs
    (matthewlboyd/freshservice-mcp `reply_to_ticket`; freshworks-api-sdk swagger `create-ticket-reply`). Not yet
    verified against a tenant. Freshservice takes no idempotency key, so send_once guards against double replies.
    """

    mode: str

    async def reply(self, ticket_id: str, body_html: str, *, idempotency_key: str) -> dict: ...


class AckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["sent", "replayed", "skipped", "failed"]
    mode: str | None = None
    reply_id: str | None = None
    reason: str | None = None


class InboundOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: RequestKind
    intent: str
    extractor: str
    run: RunView | None = None
    answer: Answer | None = None
    note: str | None = None
    ack: AckResult | None = None      # requests: the acknowledgement on the ticket
    reply: AckResult | None = None    # queries: the answer on the ticket


async def _reply_safely(replier: TicketReplier, send: Awaitable[AckResult], what: str) -> AckResult:
    """A failed ticket reply never undoes what the door already did; nothing is recorded, so a retry sends it."""
    try:
        return await send
    except ConnectorError as e:
        log.warning(f"{what}_failed", error=str(e))
        return AckResult(outcome="failed", mode=replier.mode, reason=str(e))


async def handle_inbound_email(door: Door, email: InboundEmail, *, extractor: IntentExtractor | None = None,
                               replier: TicketReplier | None = None) -> InboundOutcome:
    intent = await classify_email(email, extractor or door.runner.d.extractor)
    base = {"kind": intent.kind, "intent": intent.intent, "extractor": intent.extractor}
    if intent.kind == "approval_reply":
        log.info("email_approval_reply_ignored", ticket_id=email.ticket_id)
        return InboundOutcome(**base, note=APPROVAL_REPLY_NOTE)
    if intent.kind == "query":
        answer = await door.answer_query(email.text, channel="email", actor_external_id=email.sender,
                                         thread_ref=email.ticket_id)
        reply = None
        if replier is not None:
            reply = await _reply_safely(replier, send_query_reply(door, replier, answer, ticket_id=email.ticket_id),
                                        "query_reply")
        return InboundOutcome(**base, answer=answer, reply=reply)
    view = await door.start_run(email.text, channel="email", actor_external_id=email.sender,
                                source_ref=email.ticket_id)
    ack = None
    if replier is not None:
        ack = await _reply_safely(replier, send_requester_ack(door, replier, view, ticket_id=email.ticket_id),
                                  "requester_ack")
    return InboundOutcome(**base, run=view, ack=ack)


# --- status and query emails: answered from stored facts, citing audit seq numbers (T236) -------------------

def render_query_reply(answer: Answer) -> str:
    """The answer door.answer_query built from stored facts, and the audit rows it came from. No model text."""
    parts = [f"<p>{_t(answer.text)}</p>"]
    if answer.citations:
        parts.append(f"<p>Sources: audit seq {_t(', '.join(map(str, answer.citations)))} (the hash-chained "
                     f"receipt of run {_t(str(answer.run_id)[:8])}).</p>")
    return "".join(parts)


async def send_query_reply(door: Door, replier: TicketReplier, answer: Answer, *,
                           ticket_id: str | None) -> AckResult:
    """Reply once per question ticket. Raises the replier's ConnectorError; records nothing then."""
    if not ticket_id:
        return AckResult(outcome="skipped", reason="no Freshservice ticket to reply on")
    body = render_query_reply(answer)

    async def deliver(key: str) -> dict:
        response = await replier.reply(ticket_id, body, idempotency_key=key)
        return {"mode": replier.mode, "ticket_id": ticket_id, "reply_id": str(response.get("id"))}

    if answer.run_id is None:  # nothing to key on in door_messages; the webhook's ticket dedupe prevents repeats
        ref = await deliver(sha256_hex({"query_reply": ticket_id}))
        return AckResult(outcome="sent", mode=ref["mode"], reply_id=ref["reply_id"])
    ref, replayed = await send_once(door.db, run_id=answer.run_id, action_id=f"query:{ticket_id}",
                                    channel="freshservice", send=deliver)
    return AckResult(outcome="replayed" if replayed else "sent", mode=ref["mode"], reply_id=ref["reply_id"])


# --- requester acknowledgement: a ticket reply rendered from RunView ------------------------------------------

ACK_ACTION_ID = "requester-ack"   # door_messages key: one acknowledgement per run on the Freshservice ticket
_STATUS_LINE = {
    "running": "We are working on it.",
    "awaiting_approval": "Some items are waiting for a named approver. This ticket is updated when they decide.",
    "partial": "Finished. Some items were refused or could not be completed; the reasons are below.",
    "done": "Done. Everything you asked for is in place and verified.",
    "failed": "This request stopped with an error before anything was changed.",
}


def _question(need: dict) -> str:
    mention, reason = need.get("mention"), need.get("reason")
    if reason == "ambiguous":
        options = " or ".join(f"{c['display_name']} ({c['team']})" for c in need.get("candidates", []))
        return f"Which {mention} do you mean: {options}?"
    if reason == "no_match":
        return f"We could not find anyone called '{mention}'. Who do you mean?"
    if reason == "same_person":
        return "The person and the one to copy access from are the same. Whose access should be copied?"
    if reason == "unclear_request":
        return "What should be done, and for whom?"
    return "Who is this request for?"


def render_requester_ack(view: RunView) -> str:
    """The acknowledgement body (HTML, as Freshservice replies are). Facts come from the view only."""
    parts = [f"<p>We received your request: “{_t(view.request_text)}”.</p>"]
    if view.status == "needs_input":
        questions = " ".join(_question(n) for n in view.needs)
        parts.append(f"<p>We need one detail before we can continue. {_t(questions)} Reply on this ticket with the "
                     "full name or ID.</p>")
    else:
        parts.append(f"<p>{_t(_STATUS_LINE.get(view.status, view.status))}</p>")
    items = []
    if view.counts.get("verified"):
        items.append(f"✅ {view.counts['verified']} done and verified")
    awaiting = [r for r in view.rows if r.state == "awaiting"]
    if awaiting:
        names = dict.fromkeys(r.approver_name or r.approver_id or "" for r in awaiting)
        items.append(f"🟠 {len(awaiting)} waiting for approval: {', '.join(names)}")
    refused = [f"{r.label} ({r.rule_id})" for r in view.rows if r.verdict == "REFUSE"]
    if refused:
        items.append(f"⛔ {len(refused)} refused: {'; '.join(refused)}")
    if items:
        parts.append("<ul>" + "".join(f"<li>{_t(i)}</li>" for i in items) + "</ul>")
    modes = ", ".join(f"{k} {v}" for k, v in view.modes.items())
    replay = " Some explanations are a recorded demo output (REPLAY)." if view.replay else ""
    parts.append(f"<p>Mode: {_t(modes)}.{replay} Reference: run {_t(str(view.run_id)[:8])}.</p>")
    return "".join(parts)


async def send_requester_ack(door: Door, replier: TicketReplier, view: RunView, *,
                             ticket_id: str | None) -> AckResult:
    """Reply once per run on the requester's ticket. Raises the replier's ConnectorError; records nothing then."""
    if not ticket_id:
        return AckResult(outcome="skipped", reason="no Freshservice ticket to reply on")
    body = render_requester_ack(view)

    async def deliver(key: str) -> dict:
        response = await replier.reply(ticket_id, body, idempotency_key=key)
        return {"mode": replier.mode, "ticket_id": ticket_id, "reply_id": str(response.get("id"))}

    ref, replayed = await send_once(door.db, run_id=view.run_id, action_id=ACK_ACTION_ID, channel="freshservice",
                                    send=deliver)
    return AckResult(outcome="replayed" if replayed else "sent", mode=ref["mode"], reply_id=ref["reply_id"])


# --- the approval email, rendered from RunView ---------------------------------------------------------------

class RenderedEmail(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    subject: str
    text: str
    html: str


def _facts(view: RunView, row: RowView, delivery_mode: str) -> list[tuple[str, str]]:
    who = f"{view.subject} (same as {view.peer})" if view.peer else (view.subject or "unknown")
    facts = [("Action", row.label), ("For", who), ("Request", f"“{view.request_text}”"), ("Rule", row.rule_id),
             ("Clause", f"“{row.clause}”")]
    if row.explanation:
        facts.append(("Why held", f"{row.explanation} ({row.explainer})"))
    facts.append(("Mode", f"email {delivery_mode}, target system {row.connector_mode}"))
    if view.replay:
        facts.append(("Note", "REPLAY: model-written text here is a recorded demo output"))
    return facts


def _wrap(text: str, indent: str = "") -> list[str]:
    return textwrap.wrap(text, width=PHONE_WIDTH, subsequent_indent=indent, break_on_hyphens=False)


def _plain(view: RunView, row: RowView, facts, approve_url: str, refuse_url: str, expires_at: datetime) -> str:
    lines = [f"{row.lamp} Approval needed", "", *_wrap(f"{row.approver_name}, you are the named approver."), ""]
    for label, value in facts:
        lines += _wrap(f"{label}: {value}", indent="  ")
    lines += ["", "Approve:", approve_url, "", "Refuse:", refuse_url, "",
              *_wrap("Each link opens a page that asks you to confirm. Nothing is decided until you press Confirm."),
              *_wrap(f"Links expire {format_ist(expires_at)}."), "",
              *_wrap(f"Run {str(view.run_id)[:8]} · case digest {(view.capsule_digest or '')[:8]}")]
    return "\n".join(lines) + "\n"


def _t(value: object) -> str:
    return html.escape(str(value), quote=False)


def _button(url: str, label: str, colour: str) -> str:
    return (f'<a href="{html.escape(url, quote=True)}" style="display:inline-block;padding:12px 26px;margin:4px 8px '
            f'4px 0;border-radius:6px;background:{colour};color:#ffffff;text-decoration:none;font-weight:bold">'
            f"{label}</a>")


def _html(view: RunView, row: RowView, facts, approve_url: str, refuse_url: str, expires_at: datetime) -> str:
    rows = "".join(
        f'<tr><td style="padding:4px 12px 4px 0;vertical-align:top;color:#5b6475;white-space:nowrap">{_t(k)}</td>'
        f'<td style="padding:4px 0">{_t(v)}</td></tr>' for k, v in facts)
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1"></head>'
        '<body style="margin:0;padding:0;background:#f6f7f9">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td style="padding:16px">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;margin:0 '
        'auto;background:#ffffff;border-radius:8px;font:15px/1.5 Arial,Helvetica,sans-serif;color:#1d2330">'
        '<tr><td style="padding:20px">'
        f'<h1 style="font-size:20px;margin:0 0 8px">{_t(row.lamp)} Approval needed: {_t(row.label)}</h1>'
        f"<p>{_t(row.approver_name)}, you are the named approver.</p>"
        f'<table role="presentation" cellpadding="0" cellspacing="0">{rows}</table>'
        f'<p style="margin:20px 0 8px">{_button(approve_url, "Approve", "#1f7a3f")}'
        f'{_button(refuse_url, "Refuse", "#b3261e")}</p>'
        '<p style="font-size:13px;color:#5b6475">Each button opens a page that asks you to confirm. Nothing is '
        f"decided until you press Confirm. Links expire {_t(format_ist(expires_at))}.</p>"
        f'<p style="font-size:12px;color:#5b6475">Run {_t(str(view.run_id)[:8])} · case digest '
        f"{_t((view.capsule_digest or '')[:8])}</p>"
        "</td></tr></table></td></tr></table></body></html>")


def render_approval_email(view: RunView, row: RowView, *, approve_url: str, refuse_url: str, delivery_mode: str,
                          expires_at: datetime) -> RenderedEmail:
    """Everything shown comes from the view: the lamp, the action, the rule and clause verbatim, the named approver,
    the explanation and who wrote it, and the honest mode of this email and of the system it would change."""
    facts = _facts(view, row, delivery_mode)
    return RenderedEmail(subject=f"{row.lamp} Approval needed: {row.label}",
                         text=_plain(view, row, facts, approve_url, refuse_url, expires_at),
                         html=_html(view, row, facts, approve_url, refuse_url, expires_at))


# --- the approval.dispatch job, for approvers whose preferred door is email -------------------------------------

@dataclass
class EmailDoorContext:
    """What the worker hands the email door. `public_url` is where /a/{token} is served."""

    door: Door
    ses: SesConnector
    signer: LinkSigner
    public_url: str
    link_ttl: timedelta = timedelta(hours=72)
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))


class EmailDispatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["sent", "replayed", "skipped"]
    reason: str | None = None
    mode: str | None = None
    message_id: str | None = None
    outbox_path: str | None = None


async def handle_approval_dispatch_email(payload: dict, ctx: EmailDoorContext) -> EmailDispatchResult:
    """Job kind 'approval.dispatch' (payload from rail/approve.dispatch_holds) when the approver prefers email."""
    run_id, action_id, approver = UUID(str(payload["run_id"])), payload["action_id"], payload["approver"]
    db = ctx.door.db
    async with db.connection() as c:
        person = await (await c.execute("select email, preferred_door from identity_map where person_id = %s",
                                        (approver,))).fetchone()
        action = await (await c.execute("select expires_at from actions where run_id = %s and id = %s",
                                        (run_id, action_id))).fetchone()
    if person is None or not person["email"]:
        return EmailDispatchResult(outcome="skipped", reason=f"no email address for {approver}")
    if person["preferred_door"] != "email":
        return EmailDispatchResult(outcome="skipped", reason=f"{approver} prefers {person['preferred_door']}")
    view = await ctx.door.get_status(run_id)
    row = next((r for r in view.rows if r.action_id == action_id), None)
    if row is None or action is None:
        return EmailDispatchResult(outcome="skipped", reason=f"no action {action_id} in run {run_id}")
    if row.state != "awaiting":
        return EmailDispatchResult(outcome="skipped", reason=f"action is {row.state}, not awaiting a decision")
    if row.params_hash != payload["params_hash"] or row.approver_id != approver:
        return EmailDispatchResult(outcome="skipped", reason="the action's parameters changed since dispatch")

    expires_at = ctx.clock() + ctx.link_ttl
    if action["expires_at"] is not None:
        expires_at = min(expires_at, action["expires_at"])
    exp = int(expires_at.timestamp())

    def url(decision: str) -> str:
        token = ctx.signer.sign(LinkClaims(run_id=run_id, action_id=action_id, params_hash=row.params_hash,
                                           approver=approver, decision=decision, exp=exp))
        return f"{ctx.public_url.rstrip('/')}/a/{token}"

    rendered = render_approval_email(view, row, approve_url=url("approved"), refuse_url=url("refused"),
                                     delivery_mode=ctx.ses.mode, expires_at=datetime.fromtimestamp(exp, UTC))
    out = await ctx.ses.send(db, run_id=run_id, action_id=action_id,
                             message=OutboundEmail(to=person["email"], **rendered.model_dump()))
    if not out.replayed:
        async with db.transaction() as c:
            await chain.append(c, run_id=run_id, event="approval.email_sent", payload={
                "action_id": action_id, "approver": approver, "mode": out.mode, "message_id": out.message_id})
    return EmailDispatchResult(outcome="replayed" if out.replayed else "sent", mode=out.mode,
                               message_id=out.message_id, outbox_path=out.outbox_path)


# --- the receipt email, on finalize (T235) ------------------------------------------------------------------

FINAL_STATUSES = {"partial", "done", "failed"}
RECEIPT_ACTION_ID = "receipt"   # door_messages key: one receipt email per run (final statuses are terminal)
_OUTCOME = {"done": "Done", "partial": "Partly done", "failed": "Stopped"}


def _receipt_sections(view: RunView) -> list[tuple[str, list[str]]]:
    """(heading, lines) groups, in the order a reader checks them: what happened, what was refused, what is left."""
    rows = view.rows
    groups = [
        (f"✅ {view.counts['verified']} done and verified", [r.label for r in rows if r.state == "verified"]),
        (f"⛔ {view.counts['refuse']} refused",
         [f"{r.label} | Rule: {r.rule_id} | Clause: “{r.clause}”" for r in rows if r.verdict == "REFUSE"]),
        (f"🟠 {view.counts['awaiting']} still waiting",
         [f"{r.label} | for {r.approver_name or r.approver_id}" for r in rows if r.state == "awaiting"]),
        (f"❗ {view.counts['failed']} failed or unconfirmed",
         [f"{r.label} ({r.state})" for r in rows if r.state in ("failed", "unknown")]),
    ]
    return [(heading, lines) for heading, lines in groups if lines]


def render_receipt_email(view: RunView, *, audit_from: int | None, audit_to: int | None,
                         delivery_mode: str) -> RenderedEmail:
    """The requester's receipt, from the view and the audit seq range it covers. No model writes any of it."""
    outcome = _OUTCOME.get(view.status, view.status)
    who = f"{view.subject} (same as {view.peer})" if view.peer else (view.subject or "")
    modes = ", ".join(f"{k} {v}" for k, v in view.modes.items())
    audit = f"seq {audit_from} to {audit_to}" if audit_from is not None else "no rows"
    digest, run = (view.capsule_digest or "")[:8], str(view.run_id)[:8]
    footer = [f"Mode: {modes}; this email {delivery_mode}.",
              f"Audit: {audit} (hash-chained); case digest {digest}; run {run}."]
    if view.replay:
        footer.insert(0, "REPLAY: model-written explanations here are a recorded demo output.")
    sections = _receipt_sections(view)
    lines = [f"Receipt · {outcome}", "", *_wrap(f"Request: “{view.request_text}”", indent="  "),
             *_wrap(f"For: {who}", indent="  ")]
    for heading, items in sections:
        lines += ["", heading]
        for item in items:
            for part in item.split(" | "):
                lines += _wrap(f"  {part}", indent="    ")
    lines += [""]
    for f in footer:
        lines += _wrap(f, indent="  ")
    blocks = "".join(
        f"<h2 style=\"font-size:16px;margin:16px 0 4px\">{_t(h)}</h2><ul>"
        + "".join(f"<li>{'<br>'.join(_t(p) for p in item.split(' | '))}</li>" for item in items) + "</ul>"
        for h, items in sections)
    html_doc = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1"></head>'
        '<body style="margin:0;padding:16px;background:#f6f7f9;font:15px/1.5 Arial,Helvetica,sans-serif;'
        'color:#1d2330"><div style="max-width:560px;margin:0 auto;background:#ffffff;border-radius:8px;'
        f'padding:20px"><h1 style="font-size:20px;margin:0 0 8px">Receipt · {_t(outcome)}</h1>'
        f"<p>Request: “{_t(view.request_text)}”<br>For: {_t(who)}</p>{blocks}"
        + "".join(f'<p style="font-size:12px;color:#5b6475">{_t(f)}</p>' for f in footer)
        + "</div></body></html>")
    return RenderedEmail(subject=f"Receipt · {outcome}: {view.request_text[:60]}", text="\n".join(lines) + "\n",
                         html=html_doc)


async def handle_receipt_email(payload: dict, ctx: EmailDoorContext) -> EmailDispatchResult:
    """Job kind 'receipt.build' (rail/finalize.request_receipt): email the requester once the run is final, when the
    request came in by email or the requester prefers email. Other requesters get their receipt in their door."""
    run_id = UUID(str(payload["run_id"]))
    view = await ctx.door.get_status(run_id)
    if view.status not in FINAL_STATUSES:
        return EmailDispatchResult(outcome="skipped", reason=f"run is {view.status}; the receipt waits for the end")
    db = ctx.door.db
    async with db.connection() as c:
        run = await (await c.execute("select source, requested_by from runs where id = %s", (run_id,))).fetchone()
        person = await (await c.execute("select email, preferred_door from identity_map where person_id = %s",
                                        (run["requested_by"],))).fetchone()
        seqs = await (await c.execute("select min(seq) as lo, max(seq) as hi from audit where run_id = %s",
                                      (run_id,))).fetchone()
    if person is None or not person["email"]:
        return EmailDispatchResult(outcome="skipped", reason="the requester has no email address on record")
    if run["source"] != "email" and person["preferred_door"] != "email":
        return EmailDispatchResult(outcome="skipped",
                                   reason=f"the requester follows this run in {person['preferred_door']}")
    rendered = render_receipt_email(view, audit_from=seqs["lo"], audit_to=seqs["hi"], delivery_mode=ctx.ses.mode)
    out = await ctx.ses.send(db, run_id=run_id, action_id=RECEIPT_ACTION_ID,
                             message=OutboundEmail(to=person["email"], **rendered.model_dump()))
    if not out.replayed:
        async with db.transaction() as c:
            await chain.append(c, run_id=run_id, event="receipt.email_sent", payload={
                "status": view.status, "mode": out.mode, "message_id": out.message_id,
                "audit_from": seqs["lo"], "audit_to": seqs["hi"]})
    return EmailDispatchResult(outcome="replayed" if out.replayed else "sent", mode=out.mode,
                               message_id=out.message_id, outbox_path=out.outbox_path)

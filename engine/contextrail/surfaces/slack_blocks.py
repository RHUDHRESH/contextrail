"""Block Kit for the Slack door: pure functions of `RunView` (and StageEvent), no I/O (CLAUDE.md §13.1, P9).

Every word a Slack user sees about a run comes from here, rendered from the same RunView every other door renders,
so Slack cannot disagree with Email, Teams, Voice or MCP about a verdict. Lamps: ✅ ALLOW, 🟠 HOLD, ⛔ REFUSE.
Text we did not write (request text, labels, clauses) is escaped: `&`, `<` and `>` are Slack's control characters
(docs.slack.dev/messaging/formatting-message-text), so a request cannot smuggle in a mention or a link.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from uuid import UUID

from contextrail.models import STAGE_ORDER, StageEvent
from contextrail.surfaces.presenter import RowView, RunView

USAGE = "Tell me what you need, in one sentence. For example: `/contextrail give Anil the same access as Rahul Mehta`"
_SECTION_MAX = 2900  # Slack's section text limit is 3000 characters

STAGE_TITLE = {
    "discover": "Finding who this is for", "compile": "Sealing the case file", "govern": "Applying written policy",
    "plan": "Planning the steps", "handoff": "Checking the seal", "approve": "Asking the named approvers",
    "execute": "Making the changes", "verify": "Reading every change back", "finalize": "Writing the receipt",
}
STATUS_LINE = {
    "running": "⏳ *Working.*",
    "needs_input": "🟠 *I need one more detail.*",
    "awaiting_approval": "🟠 *Waiting for approval.*",
    "partial": "⛔ *Finished. Some items were refused or failed.*",
    "done": "✅ *Done. Everything was verified.*",
    "failed": "⛔ *Stopped. Nothing more will happen on this run.*",
}


def esc(text: str | None) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def ack_text(request_text: str) -> str:
    return f"Got it: “{esc(request_text)}”. I'll post progress here."


def _section(text: str) -> dict:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text[:3000]}}


def _context(text: str) -> dict:
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text[:3000]}]}


def digest_short(digest: str | None) -> str:
    return f"{digest[:4]}…{digest[-2:]}" if digest else "not sealed"


def counts_line(counts: dict[str, int]) -> str:
    line = f"✅ {counts.get('verified', 0)} verified · 🟠 {counts.get('awaiting', 0)} waiting · " \
           f"⛔ {counts.get('refuse', 0)} refused"
    return line + (f" · {counts['failed']} failed" if counts.get("failed") else "")


def context_line(view: RunView) -> str:
    modes = ", ".join(f"{name} {mode}" for name, mode in view.modes.items())
    return (f"Run `{str(view.run_id)[:8]}` · case {digest_short(view.capsule_digest)} · {modes}"
            + (" · replay" if view.replay else ""))


# --- the run status message (one per run, edited in place) -------------------------------------------------------

def starting_message(request_text: str) -> dict:
    return {"text": f"Starting: {request_text}",
            "blocks": [_section(f"⏳ *Starting.*\n“{esc(request_text)}”")]}


def stage_message(request_text: str, event: StageEvent) -> dict:
    """While the rail runs: which step, in plain words, and the rail's own one-line message for it."""
    stage = str(event.stage)
    step = STAGE_ORDER.index(event.stage) + 1
    title = STAGE_TITLE.get(stage, stage)
    return {"text": f"{title}: {event.message}",
            "blocks": [_section(f"⏳ *Step {step} of {len(STAGE_ORDER)} · {title}*\n{esc(event.message)}"),
                       _context(f"“{esc(request_text)}”" + (" · replay" if event.replay else ""))]}


def row_line(r: RowView) -> str:
    who = esc(r.approver_name or r.approver_id)
    if r.verdict == "REFUSE":
        return f"{r.lamp} ~{esc(r.label)}~ · {esc(r.rule_id)}: {esc(r.clause)}"
    if r.verdict == "HOLD":
        detail = {"awaiting": f"waiting for {who}", "refused": f"refused by {who}",
                  "verified": f"approved by {who} · verified"}.get(r.state, f"approved by {who} · {r.state}")
    else:
        detail = "verified" if r.verified else r.state
    return f"{r.lamp} {esc(r.label)} · {detail}"


def _row_sections(rows: list[RowView]) -> list[dict]:
    sections, chunk = [], ""
    for line in (row_line(r) for r in rows):
        if chunk and len(chunk) + len(line) + 1 > _SECTION_MAX:
            sections.append(_section(chunk))
            chunk = ""
        chunk = f"{chunk}\n{line}" if chunk else line
    return sections + ([_section(chunk)] if chunk else [])


# --- the approval card (the approver's DM) -----------------------------------------------------------------------

def decision_value(view: RunView, row: RowView) -> str:
    """What both buttons carry back: the exact action and the exact parameters the approver saw (P0-5)."""
    return f"{view.run_id}|{row.action_id}|{row.params_hash}"


_DECISION_VALUE = re.compile(r"^(?P<run>[0-9a-f-]{36})\|(?P<action>[^|]{1,200})\|(?P<hash>[0-9a-f]{64})$")


def parse_decision_value(value: str | None) -> tuple[UUID, str, str] | None:
    """(run_id, action_id, params_hash) from a button, or None if it is not exactly what decision_value makes.
    A well-formed value proves nothing: Door.decide still checks the actor, the state and the params_hash."""
    m = _DECISION_VALUE.match(value or "")
    if m is None:
        return None
    try:
        return UUID(m["run"]), m["action"], m["hash"]
    except ValueError:
        return None


def _card_body(view: RunView, row: RowView, *, title: str) -> list[dict]:
    lines = [f"*{esc(view.subject or 'Unknown subject')}* · requested: “{esc(view.request_text)}”",
             f"*Action:* {esc(row.kind)} · {esc(row.label)}",
             f"*Rule:* {esc(row.rule_id)} — {esc(row.clause)}",
             f"*Approver:* {esc(row.approver_name or row.approver_id)}"]
    if row.explanation:
        lines.append(f"*Why:* {esc(row.explanation)}")
    return [{"type": "header", "text": {"type": "plain_text", "text": f"{title} · {row.label}"[:150]}},
            _section("\n".join(lines)),
            _context(f"{context_line(view)} · this action: {row.connector_mode}")]


def approval_card(view: RunView, row: RowView) -> dict:
    """Header, who and what, the deciding rule and its clause verbatim, the named approver, the explanation, the
    honest modes, and Approve / Refuse bound to (run_id, action_id, params_hash)."""
    value = decision_value(view, row)
    buttons = [{"type": "button", "action_id": "approve", "style": "primary", "value": value,
                "text": {"type": "plain_text", "text": "Approve"}},
               {"type": "button", "action_id": "refuse", "style": "danger", "value": value,
                "text": {"type": "plain_text", "text": "Refuse"}}]
    return {"text": f"Approval needed: {row.label} for {view.subject or 'a request'}",
            "blocks": [*_card_body(view, row, title="Approval needed"),
                       {"type": "actions", "block_id": "decision", "elements": buttons}]}


DOOR_NAME = {"slack": "Slack", "teams": "Teams", "email": "email", "voice": "a phone call",
             "freshservice": "Freshservice", "mcp": "MCP"}


def slack_date(at: datetime) -> str:
    """Slack renders <!date^...> in each reader's own time zone; the fallback is UTC."""
    at = at.astimezone(UTC)
    return f"<!date^{int(at.timestamp())}^{{date_short_pretty}} at {{time}}|{at:%Y-%m-%d %H:%M} UTC>"


def decided_card(view: RunView, row: RowView, decision: dict) -> dict:
    """The card after a decision in any door: who, in which door, when, the outcome; no buttons left to press.
    `decision` is the stored approvals row (approver, decision, channel, decided_at, reason)."""
    approved = decision["decision"] == "approved"
    who = row.approver_name if decision["approver"] == row.approver_id and row.approver_name else decision["approver"]
    door = DOOR_NAME.get(decision["channel"], decision["channel"])
    outcome = "Approved" if approved else "Refused"
    line = f"{'✅' if approved else '⛔'} *{outcome}* by {esc(who)} in {door} · {slack_date(decision['decided_at'])}"
    if decision.get("reason"):
        line += f"\n*Reason:* {esc(decision['reason'])}"
    return {"text": f"{outcome} by {who} in {door}: {row.label}",
            "blocks": [*_card_body(view, row, title=outcome), _section(line)]}


def rejected_text(reason: str | None) -> str:
    """What the clicker sees when the Door did not record their click. The reason is the Door's, verbatim."""
    return f"⛔ Not recorded: {esc(reason or 'the decision was rejected')}."


# --- needs_input: ask, never guess (P1, X1) ----------------------------------------------------------------------

EXAMPLE = "`/contextrail give Anil the same access as Rahul Mehta`"


def pick_value(run_id: UUID, role: str, source_id: str) -> str:
    return f"{run_id}|{role}|{source_id}"


_PICK_VALUE = re.compile(r"^(?P<run>[0-9a-f-]{36})\|(?P<role>subject|peer)\|(?P<id>[A-Za-z0-9_.-]{1,64})$")


def parse_pick_value(value: str | None) -> tuple[UUID, str, str] | None:
    """(run_id, role, source_id) from a candidate button, or None. The rail still looks the ID up exactly."""
    m = _PICK_VALUE.match(value or "")
    if m is None:
        return None
    try:
        return UUID(m["run"]), m["role"], m["id"]
    except ValueError:
        return None


def not_yours_text(asker: str) -> str:
    return f"🟠 Only <@{asker}> can answer this. They asked for it."


ANSWERED_TEXT = "🟠 This question was already answered."


def _question(need: dict) -> str:
    mention, reason = esc(need.get("mention")), need.get("reason")
    if reason == "ambiguous":
        return f"Which *{mention}* do you mean?"
    if reason == "no_match":
        return f"I couldn't find *{mention}*. Try again with their full name or employee ID."
    if reason == "same_person":
        return f"*{mention}* is the person this is for. Whose access should be copied?"
    if reason == "unclear_request":
        return f"What should be done, and for whom? For example: {EXAMPLE}"
    return "Who is this for?" if need.get("role") == "subject" else "Whose access should be copied?"


def _candidate_label(c: dict) -> str:
    return f"{c['display_name']} · {c.get('team') or c.get('role') or c.get('employment_type')}"[:75]


def needs_input_message(view: RunView) -> dict:
    """The rail stopped rather than guess who someone is. One question per open need; a button per exact match.
    Each button carries run|role|source_id, and the rail still looks the pick up by ID."""
    body = [_section(f"{STATUS_LINE['needs_input']}\n“{esc(view.request_text)}”")]
    for i, need in enumerate(view.needs):
        body.append(_section(_question(need)))
        candidates = need.get("candidates") or []
        if candidates:
            body.append({"type": "actions", "block_id": f"pick:{i}", "elements": [
                {"type": "button", "action_id": f"pick_candidate:{j}", "text": {"type": "plain_text",
                                                                                "text": _candidate_label(c)},
                 "value": pick_value(view.run_id, need["role"], c["source_id"])}
                for j, c in enumerate(candidates[:25])]})     # Slack allows 25 elements per actions block
    body.append(_context(context_line(view)))
    return {"text": f"I need one more detail: {view.request_text}", "blocks": body}


def run_summary(view: RunView) -> dict:
    """When the rail pauses or ends: the whole RunView, every row with its lamp, refusals struck through (P4)."""
    if view.status == "needs_input" and view.needs:
        return needs_input_message(view)
    head = f"{STATUS_LINE.get(view.status, view.status)}\n“{esc(view.request_text)}”"
    who = f"*For:* {esc(view.subject)}" + (f" · same as {esc(view.peer)}" if view.peer else "") if view.subject else ""
    body = [_section(head + (f"\n{who}" if who else ""))]
    body += _row_sections(view.rows)
    if view.rows:
        body.append(_context(counts_line(view.counts)))
    body.append(_context(context_line(view)))
    return {"text": f"{STATUS_LINE.get(view.status, view.status).replace('*', '')} {view.request_text}",
            "blocks": body}

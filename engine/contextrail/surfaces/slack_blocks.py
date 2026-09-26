"""Block Kit for the Slack door: pure functions of `RunView` (and StageEvent), no I/O (CLAUDE.md §13.1, P9).

Every word a Slack user sees about a run comes from here, rendered from the same RunView every other door renders,
so Slack cannot disagree with Email, Teams, Voice or MCP about a verdict. Lamps: ✅ ALLOW, 🟠 HOLD, ⛔ REFUSE.
Text we did not write (request text, labels, clauses) is escaped: `&`, `<` and `>` are Slack's control characters
(docs.slack.dev/messaging/formatting-message-text), so a request cannot smuggle in a mention or a link.
"""

from __future__ import annotations

import re
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


def _card_body(view: RunView, row: RowView) -> list[dict]:
    lines = [f"*{esc(view.subject or 'Unknown subject')}* · requested: “{esc(view.request_text)}”",
             f"*Action:* {esc(row.kind)} · {esc(row.label)}",
             f"*Rule:* {esc(row.rule_id)} — {esc(row.clause)}",
             f"*Approver:* {esc(row.approver_name or row.approver_id)}"]
    if row.explanation:
        lines.append(f"*Why:* {esc(row.explanation)}")
    return [{"type": "header", "text": {"type": "plain_text", "text": f"Approval needed · {row.label}"[:150]}},
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
            "blocks": [*_card_body(view, row), {"type": "actions", "block_id": "decision", "elements": buttons}]}


def run_summary(view: RunView) -> dict:
    """When the rail pauses or ends: the whole RunView, every row with its lamp, refusals struck through (P4)."""
    head = f"{STATUS_LINE.get(view.status, view.status)}\n“{esc(view.request_text)}”"
    who = f"*For:* {esc(view.subject)}" + (f" · same as {esc(view.peer)}" if view.peer else "") if view.subject else ""
    body = [_section(head + (f"\n{who}" if who else ""))]
    body += _row_sections(view.rows)
    if view.rows:
        body.append(_context(counts_line(view.counts)))
    body.append(_context(context_line(view)))
    return {"text": f"{STATUS_LINE.get(view.status, view.status).replace('*', '')} {view.request_text}",
            "blocks": body}

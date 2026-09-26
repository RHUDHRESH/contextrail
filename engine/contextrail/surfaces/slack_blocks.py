"""Block Kit for the Slack door: pure functions of `RunView` (and StageEvent), no I/O (CLAUDE.md §13.1, P9).

Every word a Slack user sees about a run comes from here, rendered from the same RunView every other door renders,
so Slack cannot disagree with Email, Teams, Voice or MCP about a verdict. Lamps: ✅ ALLOW, 🟠 HOLD, ⛔ REFUSE.
Text we did not write (request text, labels, clauses) is escaped: `&`, `<` and `>` are Slack's control characters
(docs.slack.dev/messaging/formatting-message-text), so a request cannot smuggle in a mention or a link.
"""

from __future__ import annotations

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

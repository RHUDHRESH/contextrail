"""Block Kit for the Slack door: pure functions of `RunView` (and StageEvent), no I/O (CLAUDE.md §13.1, P9).

Every word a Slack user sees about a run comes from here, rendered from the same RunView every other door renders,
so Slack cannot disagree with Email, Teams, Voice or MCP about a verdict. Lamps: ✅ ALLOW, 🟠 HOLD, ⛔ REFUSE.
Text we did not write (request text, labels, clauses) is escaped: `&`, `<` and `>` are Slack's control characters
(docs.slack.dev/messaging/formatting-message-text), so a request cannot smuggle in a mention or a link.
"""

from __future__ import annotations

USAGE = "Tell me what you need, in one sentence. For example: `/contextrail give Anil the same access as Rahul Mehta`"


def esc(text: str | None) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def ack_text(request_text: str) -> str:
    return f"Got it: “{esc(request_text)}”. I'll post progress here."

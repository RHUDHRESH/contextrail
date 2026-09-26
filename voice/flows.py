"""The door flows the phone runs (CLAUDE.md §13.3 items 5-7). Each is code, not model output: it reads back,
confirms, calls the engine's door contract, and speaks what the engine returned. Nothing here decides a verdict,
an approval or whether anything is verified; the engine does (D-005).

A flow gets the Dialogue and what the caller said, and returns the lines to say. When it needs the caller's next
answer (yes/no after a read-back), it sets dialogue.expect to the handler for that answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import partial
from typing import TYPE_CHECKING
from uuid import UUID

from engine_client import DecisionResult, EngineError, RowView, RunView
from intents import asks_to_request, match_next, match_yes_no

if TYPE_CHECKING:
    from dialogue import Dialogue


@dataclass
class Turn:
    say: list[str] = field(default_factory=list)
    control: str | None = None  # "gather_dtmf" or "transfer": the call must leave the media stream

# High-risk items (CLAUDE.md §13.3 item 7, §16: "terminal-adjacent, production-tagged") are never decided by phone.
# The phone cannot hold half an approval (the engine's first decision wins), so these need a tap in Slack or Teams.
# This only narrows what the phone may do; the engine still decides whether any decision is valid.
HIGH_RISK_RULES = frozenset({
    "POL-ACC-003",  # administrator rights
    "POL-ACC-004",  # production-tagged repositories
    "POL-EMG-001",  # emergency production access
    "POL-DAT-001",  # raw customer PII
})
_KEYS = {"1": "approved", "2": "refused"}


def spoken_ref(run_id: UUID) -> str:
    """The run's reference as the caller hears it: its first 8 characters, one at a time ("A 3 F 9 1 C 2 E")."""
    return " ".join(run_id.hex[:8].upper())


def summary(d: Dialogue, view: RunView) -> list[str]:
    """The engine's own status and counts for a run, in the call's language. Nothing here is inferred."""
    status = d.lang.lines.get(f"st_{view.status}", view.status)
    c = view.counts
    return [d.line("status").format(status=status),
            d.line("counts").format(allow=c.get("allow", 0), hold=c.get("hold", 0), refuse=c.get("refuse", 0))]


# --- request: listen -> read back -> confirm -> start the run -> speak the reference (T201) ------------------

async def request_flow(d: Dialogue, text: str) -> list[str]:
    if asks_to_request(text):
        d.expect = _read_back
        return [d.line("ask_request")]
    return await _read_back(d, text)


async def _read_back(d: Dialogue, text: str) -> list[str]:
    d.expect = partial(_confirm_request, text)
    return [d.line("readback").format(text=text)]


async def _confirm_request(text: str, d: Dialogue, answer: str) -> list[str]:
    yes = match_yes_no(answer)
    if yes is None:
        d.expect = partial(_confirm_request, text)
        return [d.line("yes_or_no")]
    if not yes:
        return [d.line("cancelled")]
    try:
        result = await d.engine.start_voice_request(text, actor=d.caller_phone, source_ref=d.call_ref)
    except EngineError:
        return [d.line("engine_down")]
    ticket = result.ticket
    ticket_line = (d.line("ticket_created").format(number=ticket.ticket_id, mode=ticket.mode)
                   if ticket.status == "verified" else d.line("ticket_unavailable"))
    return [d.line("started").format(ref=spoken_ref(result.run.run_id)), ticket_line,
            *summary(d, result.run)]


# --- status and policy questions: the engine's words only (T202) ---------------------------------------------

async def query_flow(d: Dialogue, text: str) -> list[str]:
    """Answered by the engine from receipts and curated OKF policy. The caller hears a fixed preface and the engine's
    text as returned: not rephrased, not translated (a translation could change a fact), never a model's guess.
    An unknown caller's question carries no identity (caller_phone is None)."""
    try:
        answer = await d.engine.answer_query(text, actor=d.caller_phone)
    except EngineError:
        return [d.line("engine_down")]
    if not answer.text.strip():
        return [d.line("no_answer")]
    return [d.line("from_records"), answer.text]


# --- approver: list pending -> spoken confirm -> DTMF 1/2 -> engine decision (T203) -----------------------------

def high_risk(row: RowView) -> bool:
    text = f"{row.label} {row.clause}".casefold()
    return row.rule_id in HIGH_RISK_RULES or "production" in text or "admin" in text


async def approve_flow(d: Dialogue, text: str) -> list[str]:
    try:
        runs = await d.engine.pending_approvals(actor=d.caller_phone)
    except EngineError:
        return [d.line("engine_down")]
    # Only rows the engine says await this very person; the engine re-checks all of it on decide.
    d.queue = [(v, r) for v in runs for r in v.rows if r.state == "awaiting" and r.approver_id == d.caller.person_id]
    d.position = 0
    if not d.queue:
        return [d.line("nothing_pending")]
    return [d.line("pending_count").format(n=len(d.queue)), *_offer(d)]


def _offer(d: Dialogue) -> list[str]:
    if d.position >= len(d.queue):
        d.queue = []
        return [d.line("no_more")]
    view, row = d.queue[d.position]
    d.expect = _choose
    return [d.line("item").format(i=d.position + 1, label=row.label, subject=view.subject or "", rule=row.rule_id),
            d.line("decide_this")]


async def _choose(d: Dialogue, said: str) -> Turn | list[str]:
    yes = match_yes_no(said)
    if yes is None and not match_next(said):
        d.expect = _choose
        return [d.line("decide_this")]
    view, row = d.queue[d.position]
    if not yes:
        d.position += 1
        return _offer(d)
    if high_risk(row):
        d.position += 1
        return [d.line("high_risk"), *_offer(d)]
    d.awaiting_keys = (view, row)
    return Turn([d.line("press_keys")], control="gather_dtmf")


async def decide_by_keys(d: Dialogue, digits: str) -> list[str]:
    """The Gather result: 1 approves, 2 refuses, anything else decides nothing. A repeated callback finds nothing
    waiting for keys and decides nothing again (and the engine's first decision wins regardless)."""
    pending, d.awaiting_keys = d.awaiting_keys, None
    if pending is None:
        return []
    view, row = pending
    d.position += 1
    decision = _KEYS.get((digits or "").strip())
    if decision is None:
        return [d.line("no_key"), *_offer(d)]
    try:
        result = await d.engine.decide(view.run_id, row.action_id, row.params_hash, actor=d.caller_phone,
                                       decision=decision)
    except EngineError:
        return [d.line("engine_down"), *_offer(d)]
    return [_outcome(d, result, decision), *_offer(d)]


def _outcome(d: Dialogue, result: DecisionResult, decision: str) -> str:
    if result.outcome == "recorded":
        return d.line(f"decided_{decision}")
    if result.outcome == "already_decided":
        if result.decided_by == d.caller.person_id:
            return d.line("already_yours")
        return d.line("already_decided").format(channel=result.decided_channel or "")
    return f"{d.line('rejected')} {result.reason or ''}".strip()  # the engine's reason, verbatim


async def human_flow(d: Dialogue, text: str) -> Turn | list[str]:
    """Hand off only when an operator number is configured; otherwise give an honest fallback."""
    if not d.transfer_available:
        return [d.line("human_unavailable")]
    return Turn([d.line("transferring")], control="transfer")

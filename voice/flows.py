"""The door flows the phone runs (CLAUDE.md §13.3 items 5-7). Each is code, not model output: it reads back,
confirms, calls the engine's door contract, and speaks what the engine returned. Nothing here decides a verdict,
an approval or whether anything is verified; the engine does (D-005).

A flow gets the Dialogue and what the caller said, and returns the lines to say. When it needs the caller's next
answer (yes/no after a read-back), it sets dialogue.expect to the handler for that answer.
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING
from uuid import UUID

from engine_client import EngineError, RunView
from intents import asks_to_request, match_yes_no

if TYPE_CHECKING:
    from dialogue import Dialogue


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
        view = await d.engine.start_run(text, actor=d.caller_phone, source_ref=d.call_ref)
    except EngineError:
        return [d.line("engine_down")]
    return [d.line("started").format(ref=spoken_ref(view.run_id)), *summary(d, view)]

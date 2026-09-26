"""Verify (CLAUDE.md §8): read back every executed action; `succeeded` is not `verified` (P3).

AI does nothing here. The connector reads the target system and reports what it actually holds. Only a matching
read-back makes an action `verified`, stamped with the time of the read. A mismatch is `failed`, and the observed
state is kept as evidence for the receipt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from contextrail.connectors.base import ConnectorError
from contextrail.models import Action, ActionState
from contextrail.rail.execute import connector_name

VERIFIABLE = {ActionState.EXECUTED, ActionState.UNKNOWN}


@dataclass(frozen=True)
class VerifyOutcome:
    action_id: str
    state: ActionState
    observed: dict = field(default_factory=dict)
    at: datetime | None = None
    note: str = ""


async def verify_action(action: Action, *, registry, now: datetime | None = None) -> VerifyOutcome:
    if action.state not in VERIFIABLE:
        raise ValueError(f"{action.id} is {action.state}; only executed or unknown actions are verified")
    connector = registry.get(connector_name(action))
    try:
        ok, observed = await connector.verify(action)
    except ConnectorError as e:
        return VerifyOutcome(action.id, ActionState.FAILED, note=f"read-back failed: {e}")
    if ok:
        return VerifyOutcome(action.id, ActionState.VERIFIED, observed, now or datetime.now(UTC))
    return VerifyOutcome(action.id, ActionState.FAILED, observed, note="read-back does not match the intended state")

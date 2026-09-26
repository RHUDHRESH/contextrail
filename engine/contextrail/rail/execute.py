"""Execute (CLAUDE.md §8): write ALLOW and approved actions through their connector, exactly once.

AI does nothing here. Every write carries idempotency_key(run_id, action_id, params_hash), so a retried job, a
replayed webhook or a double-clicked button writes once. Transient failures (429/5xx) back off and retry. A
permanent error fails the action. A timeout is `unknown`: never blind-retried.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from contextrail.canonical import idempotency_key
from contextrail.connectors.base import ConnectorError, TransientError, UnknownOutcome
from contextrail.models import Action, ActionState

EXECUTABLE = {(ActionState.PLANNED, "ALLOW"), (ActionState.APPROVED, "HOLD")}


def connector_name(action: Action) -> str:
    return "github" if action.target.get("system") == "github" else "entitlements"


def is_executable(action: Action) -> bool:
    return (action.state, action.verdict) in EXECUTABLE


@dataclass(frozen=True)
class ExecOutcome:
    action_id: str
    state: ActionState
    attempts: int
    replayed: bool = False
    note: str = ""


def default_backoff(attempt: int) -> float:
    return min(0.5 * 2**attempt, 8.0)


async def execute_action(action: Action, *, run_id: UUID, registry, max_attempts: int = 3,
                         backoff: Callable[[int], float] = default_backoff,
                         sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> ExecOutcome:
    """T103: one action through its connector with idempotency and bounded backoff on transient errors."""
    if not is_executable(action):
        raise ValueError(f"{action.id} is {action.verdict}/{action.state}; only ALLOW-planned or approved execute")
    connector = registry.get(connector_name(action))
    key = idempotency_key(run_id, action.id, action.params_hash)
    for attempt in range(1, max_attempts + 1):
        try:
            result = await connector.write(action, key)
            return ExecOutcome(action.id, ActionState.EXECUTED, attempt, result.replayed)
        except TransientError as e:
            if attempt == max_attempts:
                return ExecOutcome(action.id, ActionState.FAILED, attempt, note=f"transient, gave up: {e}")
            await sleep(backoff(attempt))
        except UnknownOutcome as e:
            # T104: never blind-retry. Read the system back first: if the change landed, we are done; if it did
            # not, retrying with the SAME idempotency key is safe; if we cannot tell, stop at 'unknown'.
            try:
                present, _ = await connector.verify(action)
            except ConnectorError:
                return ExecOutcome(action.id, ActionState.UNKNOWN, attempt, note=f"{e}; reconcile read failed")
            if present:
                return ExecOutcome(action.id, ActionState.EXECUTED, attempt, note="reconciled: change was applied")
            if attempt == max_attempts:
                return ExecOutcome(action.id, ActionState.UNKNOWN, attempt, note=f"{e}; not applied, out of attempts")
            await sleep(backoff(attempt))
        except ConnectorError as e:
            return ExecOutcome(action.id, ActionState.FAILED, attempt, note=f"permanent: {e}")
    raise AssertionError("unreachable")

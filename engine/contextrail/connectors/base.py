"""The connector contract (CLAUDE.md §12).

`write()` is not success: it is a claim. `verify()` reads the target system back and says whether the intended
state is really there (P3). A write that times out raises `UnknownOutcome`; the rail must reconcile with
`verify()` before any retry, never blind-retry (§8 Execute).
"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from contextrail.models import Action

Mode = Literal["LIVE", "FIXTURE", "ONE-WAY"]


class WriteResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ok: bool                 # the system acknowledged the write (a 2xx); NOT proof the state changed
    replayed: bool = False   # this idempotency key was already applied; nothing was written again
    ref: dict = {}           # system reference: {"repo": ..., "login": ...}, a ticket id, etc.
    mode: Mode


class ConnectorError(Exception):
    """Permanent failure (4xx other than 429): do not retry."""


class TransientError(ConnectorError):
    """429 / 5xx: safe to retry with backoff."""


class UnknownOutcome(ConnectorError):
    """Timed out or connection dropped after sending: the write may or may not have happened. Reconcile first."""


@runtime_checkable
class Connector(Protocol):
    name: str
    mode: Mode

    async def read(self, ref: dict) -> dict: ...

    async def write(self, action: Action, idem_key: str) -> WriteResult: ...

    async def verify(self, action: Action) -> tuple[bool, dict]: ...

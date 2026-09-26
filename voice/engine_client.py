"""The voice door's only way into ContextRail: the engine's HTTP door (/v1), with `Authorization: Bearer ENGINE_TOKEN`.

The voice service decides nothing (D-005). It forwards what the caller said and who the verified caller is, and
speaks what the engine returns. The engine maps the caller through identity_map.phone, applies policy, checks the
named approver, params_hash and POL-SOD-001, and the first decision from any door wins.

Calls (voice/README.md, "Engine API", has the full table):
- POST /v1/runs, GET /v1/runs/{id}, POST /v1/runs/{id}/decisions: match engine/contextrail/surfaces/rest.py on
  sec/P-platform exactly (door.start_run, door.get_status, door.decide).
- POST /v1/queries, POST /v1/identities/resolve, POST /v1/approvals/pending: not in the engine yet; defined here
  as thin wrappers over door.answer_query, door.resolve_actor and the awaiting rows of RunView. Phone numbers go
  in request bodies, never in URLs, so they stay out of access logs (CLAUDE.md §16).

The models mirror the engine's RunView / DecisionResult / Answer and ignore fields they do not use, so the engine
can add fields without breaking a live call.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict

CHANNEL = "voice"
_PLACEHOLDER_TOKEN = "change-me"


class _View(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class RowView(_View):
    action_id: str
    kind: str
    label: str
    verdict: Literal["ALLOW", "HOLD", "REFUSE"]
    state: str
    rule_id: str
    clause: str
    approver_id: str | None = None
    approver_name: str | None = None
    verified: bool
    params_hash: str
    connector_mode: str


class RunView(_View):
    run_id: UUID
    status: str
    request_text: str
    subject: str | None = None
    peer: str | None = None
    rows: list[RowView] = []
    counts: dict[str, int] = {}
    modes: dict[str, str] = {}
    replay: bool = False


class DecisionResult(_View):
    outcome: Literal["recorded", "already_decided", "rejected"]
    reason: str | None = None
    rule_id: str | None = None
    decided_by: str | None = None
    decided_channel: str | None = None
    view: RunView | None = None


class Answer(_View):
    text: str
    run_id: UUID | None = None
    citations: list[int] = []


class Caller(_View):
    person_id: str
    display_name: str


class EngineError(Exception):
    """The engine could not be reached, refused the token, or failed. The caller hears a fixed line, never a guess."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class EngineClient:
    def __init__(self, base_url: str, token: str, *, transport: httpx.AsyncBaseTransport | None = None,
                 timeout: float = 10.0) -> None:
        self.configured = bool(token) and token != _PLACEHOLDER_TOKEN
        self._http = httpx.AsyncClient(base_url=base_url.rstrip("/"), transport=transport, timeout=timeout,
                                       headers={"Authorization": f"Bearer {token}"})

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _call(self, method: str, path: str, body: dict | None = None, *,
                    missing_ok: bool = False) -> dict | None:
        if not self.configured:
            raise EngineError("ENGINE_TOKEN is not set; the voice door cannot reach the engine")
        try:
            r = await self._http.request(method, path, json=body)
        except httpx.HTTPError as e:
            raise EngineError(f"engine unreachable: {type(e).__name__}") from e
        if missing_ok and r.status_code == 404:
            return None
        if r.status_code >= 400:
            raise EngineError(f"engine answered {r.status_code} for {method} {path}", r.status_code)
        return r.json()

    # --- the door contract (CLAUDE.md §13.0) ------------------------------------------------------------------

    async def start_run(self, text: str, *, actor: str, source_ref: str | None) -> RunView:
        return RunView.model_validate(await self._call("POST", "/v1/runs", {
            "request_text": text, "channel": CHANNEL, "actor_external_id": actor, "source_ref": source_ref}))

    async def get_status(self, run_id: UUID) -> RunView:
        return RunView.model_validate(await self._call("GET", f"/v1/runs/{run_id}"))

    async def decide(self, run_id: UUID, action_id: str, params_hash: str, *, actor: str,
                     decision: Literal["approved", "refused"], reason: str | None = None) -> DecisionResult:
        return DecisionResult.model_validate(await self._call("POST", f"/v1/runs/{run_id}/decisions", {
            "action_id": action_id, "params_hash": params_hash, "channel": CHANNEL, "actor_external_id": actor,
            "decision": decision, "reason": reason}))

    async def answer_query(self, question: str, *, actor: str | None) -> Answer:
        """Answered by the engine from receipts and curated OKF only; unknown callers send no identity."""
        return Answer.model_validate(await self._call("POST", "/v1/queries", {
            "question": question, "channel": CHANNEL, "actor_external_id": actor}))

    # --- lookups the phone needs before it can use the contract -----------------------------------------------

    async def resolve_caller(self, phone: str) -> Caller | None:
        """identity_map.phone -> person, or None for an unregistered number."""
        data = await self._call("POST", "/v1/identities/resolve", {"channel": CHANNEL, "external_id": phone},
                                missing_ok=True)
        return Caller.model_validate(data) if data else None

    async def pending_approvals(self, *, actor: str) -> list[RunView]:
        """Runs holding at least one row awaiting this caller's decision."""
        data = await self._call("POST", "/v1/approvals/pending", {"channel": CHANNEL, "actor_external_id": actor})
        return [RunView.model_validate(v) for v in data["runs"]]

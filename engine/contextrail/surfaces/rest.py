"""The HTTP door: the door contract over /v1, for the FDK ticket sidebar, the glass box and other agents.

Every route calls surfaces/door.py and returns what every other door renders: RunView or DecisionResult (D-005).
Nothing here decides. The door maps the actor through identity_map, checks the named approver, params_hash and
POL-SOD-001, and the first decision from any door wins.

Auth: `Authorization: Bearer <ENGINE_TOKEN>`, compared in constant time. An empty or placeholder ('change-me')
token closes the API (503) rather than leaving it open. The token holder is a trusted client (the FDK app, an MCP
bridge) that asserts which person is acting; that assertion still has to pass every check in door.decide.

POST /v1/runs runs the first pass synchronously through Door.start_run, the same call Slack, Teams and Voice make,
and returns the finished RunView (awaiting_approval, needs_input, partial or done), which the sidebar renders at
once. Webhook-started runs use the 'rail.run' job instead, so the webhook can answer 202 immediately. A ticket gets
one run: a second POST for the same ticket returns the existing run with 200 (intake.py).

GET /v1/runs/{id}/events streams the run's StageEvents as Server-Sent Events (sse.py). A browser EventSource cannot
send the bearer header, so browser clients go through a server-side proxy (the glass box) or use fetch streaming.
"""

from __future__ import annotations

import hmac
from collections.abc import AsyncIterable
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, ConfigDict, Field

from contextrail import repo
from contextrail.intake import TICKET_CHANNELS, find_ticket_run, run_lock, ticket_lock
from contextrail.surfaces.door import Channel, DecisionResult
from contextrail.surfaces.presenter import RunView
from contextrail.surfaces.sse import stage_events

_PLACEHOLDER_TOKEN = "change-me"
_bearer = HTTPBearer(auto_error=False)


async def require_engine_token(
        request: Request, creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]) -> None:
    expected = request.app.state.platform.settings.engine_token.get_secret_value()
    if not expected or expected == _PLACEHOLDER_TOKEN:
        raise HTTPException(503, "ENGINE_TOKEN is not configured; the runs API stays closed until it is set")
    if creds is None or not hmac.compare_digest(creds.credentials.encode(), expected.encode()):
        raise HTTPException(401, "missing or invalid bearer token", headers={"WWW-Authenticate": "Bearer"})


router = APIRouter(prefix="/v1", tags=["runs"], dependencies=[Depends(require_engine_token)])


class StartRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_text: str = Field(min_length=1, max_length=4000)
    channel: Channel
    actor_external_id: str = Field(min_length=1, max_length=256)
    source_ref: str | None = Field(default=None, min_length=1, max_length=128)  # ticket id, slack ts, call id


class Pick(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["subject", "peer"]
    source_id: str = Field(min_length=1, max_length=64)


class Decide(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str = Field(min_length=1, max_length=64)
    params_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    channel: Channel
    actor_external_id: str = Field(min_length=1, max_length=256)
    decision: Literal["approved", "refused"]
    reason: str | None = Field(default=None, max_length=1000)


def _platform(request: Request):
    return request.app.state.platform


async def _view_or_404(platform, run_id: UUID) -> RunView:
    try:
        return await platform.door.get_status(run_id)
    except LookupError:
        raise HTTPException(404, f"no run {run_id}") from None


@router.post("/runs", response_model=RunView, status_code=201,
             responses={200: {"model": RunView, "description": "This ticket already has a run; it is returned"}})
async def start_run(body: StartRun, request: Request, response: Response) -> RunView:
    p = _platform(request)
    if body.channel in TICKET_CHANNELS and body.source_ref:
        async with ticket_lock(p.db, body.source_ref) as c:
            existing = await find_ticket_run(c, body.source_ref)
            if existing:
                response.status_code = 200
                view = await p.door.get_status(existing["id"])
            else:
                view = await p.door.start_run(body.request_text, channel=body.channel,
                                              actor_external_id=body.actor_external_id, source_ref=body.source_ref)
    else:
        view = await p.door.start_run(body.request_text, channel=body.channel,
                                      actor_external_id=body.actor_external_id, source_ref=body.source_ref)
    response.headers["Location"] = f"/v1/runs/{view.run_id}"
    return view


@router.get("/runs/by-ticket/{ticket_id}", response_model=RunView)
async def run_by_ticket(ticket_id: Annotated[str, Path(min_length=1, max_length=128)], request: Request) -> RunView:
    p = _platform(request)
    async with p.db.connection() as c:
        run = await find_ticket_run(c, ticket_id)
    if run is None:
        raise HTTPException(404, f"no run for ticket {ticket_id}")
    return await _view_or_404(p, run["id"])


@router.get("/runs/{run_id}", response_model=RunView)
async def get_run(run_id: UUID, request: Request) -> RunView:
    return await _view_or_404(_platform(request), run_id)


@router.post("/runs/{run_id}/pick", response_model=RunView)
async def pick_candidate(run_id: UUID, body: Pick, request: Request) -> RunView:
    p = _platform(request)
    async with run_lock(p.db, run_id) as c:
        run = await repo.get_run(c, run_id)
        if run is None:
            raise HTTPException(404, f"no run {run_id}")
        if run["status"] != "needs_input":
            raise HTTPException(409, f"run is {run['status']}; a candidate can only be picked while it needs input")
        return await p.door.pick_candidate(run_id, body.role, body.source_id)


@router.post("/runs/{run_id}/decisions", response_model=DecisionResult)
async def decide(run_id: UUID, body: Decide, request: Request) -> DecisionResult:
    """Every outcome (recorded, already_decided, rejected) is a governed answer, returned with 200 like any door."""
    return await _platform(request).door.decide(
        run_id, body.action_id, body.params_hash, channel=body.channel, actor_external_id=body.actor_external_id,
        decision=body.decision, reason=body.reason)


async def _existing_run(run_id: UUID, request: Request) -> UUID:
    """Resolved before the stream starts, so an unknown run is a 404, not a 200 that ends at once."""
    async with _platform(request).db.connection() as c:
        if await repo.get_run(c, run_id) is None:
            raise HTTPException(404, f"no run {run_id}")
    return run_id


@router.get("/runs/{run_id}/events", response_class=EventSourceResponse)
async def run_events(run_id: Annotated[UUID, Depends(_existing_run)], request: Request,
                     last_event_id: Annotated[int | None, Header()] = None) -> AsyncIterable[ServerSentEvent]:
    """StageEvents as Server-Sent Events: history, then live, until the run is partial, done or failed (sse.py)."""
    p = _platform(request)

    async def status() -> str | None:
        async with p.db.connection() as c:
            run = await repo.get_run(c, run_id)
        return run["status"] if run else None

    async for item in stage_events(p.events, run_id, status, heartbeat_s=p.sse_heartbeat_s,
                                   after_seq=last_event_id):
        yield item

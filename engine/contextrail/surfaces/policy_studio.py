"""GET /v1/policy/studio: Policy Studio over a stored run (checklist T072).

`?run_id=<uuid>&hold_out=<POL-XXX-000>` re-evaluates the run's sealed case file with today's rules, with and
without the held-out rule, and returns the verdict diff per action and the blast radius (policy/studio.py).
It reads the capsule through the same verified load as every later stage (P5): a case file that fails its digest
check is refused, not simulated. It writes nothing, so it adds no audit row.

The route reads the engine's database pool and policy engine from `app.state.platform.runner` (the Platform
composition root). Without a platform there is no database, and the route answers 503 rather than guessing.
Run contents are private, so the route sits behind `Authorization: Bearer <ENGINE_TOKEN>` with the same contract
as the runs API: constant-time compare, 401 on a missing or wrong token, 503 while the token is unset or 'change-me'.
"""

from __future__ import annotations

import hmac
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from contextrail import repo
from contextrail.capsule import DigestMismatch
from contextrail.db import Database
from contextrail.policy.engine import PolicyEngine
from contextrail.policy.studio import StudioReport, UnknownRule, simulate_hold_out
from contextrail.rail.compile import role_entry
from contextrail.rail.store import load_case

_PLACEHOLDER_TOKEN = "change-me"
_bearer = HTTPBearer(auto_error=False)
RULE_ID = r"^POL-[A-Z]{3}-\d{3}$"


class RunNotFound(LookupError):
    pass


async def simulate_stored_run(db: Database, engine: PolicyEngine, run_id: UUID, rule_id: str) -> StudioReport:
    """Load a run's verified case file and simulate holding `rule_id` out, with the role entry and requester Govern
    used. Raises RunNotFound, LookupError (no sealed case file yet), DigestMismatch or UnknownRule."""
    async with db.connection() as c:
        run = await repo.get_run(c, run_id)
        if run is None:
            raise RunNotFound(f"no run {run_id}")
        case = await load_case(c, run_id)
    return simulate_hold_out(case, engine, rule_id, role=role_entry(case.subject.role),
                             requested_by=run["requested_by"])


async def require_engine_token(
        request: Request, creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]) -> None:
    expected = request.app.state.settings.engine_token.get_secret_value()
    if not expected or expected == _PLACEHOLDER_TOKEN:
        raise HTTPException(503, "ENGINE_TOKEN is not configured; Policy Studio stays closed until it is set")
    if creds is None or not hmac.compare_digest(creds.credentials.encode(), expected.encode()):
        raise HTTPException(401, "missing or invalid bearer token", headers={"WWW-Authenticate": "Bearer"})


router = APIRouter(prefix="/v1/policy", tags=["policy"], dependencies=[Depends(require_engine_token)])


@router.get("/studio", response_model=StudioReport)
async def policy_studio(request: Request, run_id: UUID,
                        hold_out: Annotated[str, Query(pattern=RULE_ID)]) -> StudioReport:
    """What would this run have done without one rule? A simulation: nothing is written."""
    platform = getattr(request.app.state, "platform", None)
    if platform is None:
        raise HTTPException(503, "Policy Studio reads stored runs, and this engine has no database platform configured")
    rail = platform.runner.d
    try:
        return await simulate_stored_run(rail.db, rail.engine, run_id, hold_out)
    except RunNotFound as e:
        raise HTTPException(404, str(e)) from None
    except UnknownRule:
        raise HTTPException(404, f"no rule {hold_out} is loaded") from None
    except DigestMismatch:
        raise HTTPException(409, "the run's case file failed its digest check; an altered capsule is not simulated") \
            from None
    except LookupError:
        raise HTTPException(409, f"run {run_id} has no sealed case file yet") from None

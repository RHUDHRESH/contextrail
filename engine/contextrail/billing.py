"""Usage billing and the pilot checkout (CLAUDE.md §14.1, checklist T206).

Every completed run (done or partial) is billed once: Finalize enqueues one `dodo.usage` job per run (deduplicated
by run id), and the job sends one Dodo usage event whose `event_id` is the run id. Dodo ignores an event_id it has
already ingested, so a retried job, a crashed worker or a second finalize can never bill a run twice. After
sending, the event is read back from Dodo (P3): `verified` is true only when Dodo returns it.

A run still waiting for approval is not billed yet; it is billed when it finishes. A failed run is not billed.
"""

from __future__ import annotations

from datetime import UTC, datetime

from psycopg import AsyncConnection
from pydantic import BaseModel, ConfigDict

from contextrail import repo
from contextrail.connectors.base import ConnectorError
from contextrail.models import CaseFile, RunStatus
from contextrail.rail.finalize import tally

USAGE_EVENT_NAME = "contextrail.governed_run"
USAGE_JOB = "dodo.usage"
COMPLETED = frozenset({RunStatus.DONE, RunStatus.PARTIAL})


async def request_usage_event(conn: AsyncConnection, case: CaseFile, status: RunStatus) -> int | None:
    """Enqueue the run's one usage event. Returns the job id, or None (not completed, or already enqueued)."""
    if status not in COMPLETED:
        return None
    payload = {"run_id": str(case.run_id), "status": str(status), "intent": case.intent,
               "action_count": len(case.actions), **tally(case), "finalized_at": datetime.now(UTC).isoformat()}
    return await repo.enqueue_job(conn, USAGE_JOB, payload, dedupe_key=f"{USAGE_JOB}:{case.run_id}")


def usage_event(payload: dict, *, customer_id: str, now: datetime) -> dict:
    """The Dodo EventInput for one run. Metadata values are scalars only (Dodo rejects objects and arrays).

    The timestamp is the send time: Dodo rejects events older than one hour, and a queued job may run later than
    the run finished. When the run finished is kept in metadata."""
    keys = ("status", "intent", "action_count", "allow", "hold", "refuse", "verified", "failed", "finalized_at")
    return {"event_id": payload["run_id"], "customer_id": customer_id, "event_name": USAGE_EVENT_NAME,
            "timestamp": now.isoformat(), "metadata": {k: payload[k] for k in keys if payload.get(k) is not None}}


class UsageResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    ingested: int          # 1 the first time; 0 when Dodo already had this run's event
    replayed: bool
    verified: bool         # the event was read back from Dodo
    mode: str
    environment: str


async def send_usage_event(dodo, payload: dict, *, now: datetime | None = None) -> UsageResult:
    """Send one run's usage event and read it back. The `dodo.usage` job handler calls this."""
    customer_id = dodo.pilot_customer_id
    if not customer_id:
        raise ConnectorError("dodo: no customer to bill; set DODO_CUSTOMER_ID to the pilot's Dodo customer id")
    event = usage_event(payload, customer_id=customer_id, now=now or datetime.now(UTC))
    ingested = await dodo.ingest_usage([event])
    seen = await dodo.get_usage_event(event["event_id"])
    verified = bool(seen) and seen["event_name"] == USAGE_EVENT_NAME and seen["customer_id"] == customer_id
    return UsageResult(event_id=event["event_id"], ingested=ingested, replayed=ingested == 0, verified=verified,
                       mode=dodo.mode, environment=dodo.environment)


class CheckoutLink(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    url: str
    session_id: str
    mode: str
    environment: str


async def pilot_checkout_link(dodo, *, return_url: str, customer_email: str | None = None,
                              customer_name: str | None = None) -> CheckoutLink:
    """A Dodo checkout session for the "ContextRail governed run" product, in test mode (or a FIXTURE link)."""
    product_id = dodo.pilot_product_id
    if not product_id:
        raise ConnectorError("dodo: no product to sell; set DODO_PRODUCT_ID to the governed-run product id")
    # Dodo's NewCustomer needs an email; without one the checkout page asks the buyer instead.
    customer = {"email": customer_email, **({"name": customer_name} if customer_name else {})} \
        if customer_email else None
    out = await dodo.create_checkout(product_id=product_id, return_url=return_url, customer=customer,
                                     metadata={"source": "contextrail-pilot"})
    if not out.get("checkout_url"):
        raise ConnectorError(f"dodo: checkout session {out.get('session_id')} returned no checkout_url")
    return CheckoutLink(url=out["checkout_url"], session_id=out["session_id"], mode=dodo.mode,
                        environment=dodo.environment)

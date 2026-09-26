"""Dodo Payments (CLAUDE.md §14, checklist T206): usage billing and the pilot checkout, in TEST MODE ONLY.

Two connectors with one interface, both honest about what they are (D-004):
- `DodoTestMode` (mode LIVE) calls Dodo through the official `dodopayments` SDK, pinned to
  https://test.dodopayments.com. There is no setting that selects live mode, and the SDK's DODO_PAYMENTS_BASE_URL
  override is ignored. Its label always says "test mode".
- `FixtureDodo` (mode FIXTURE) is used whenever no DODO_API_KEY is configured. It keeps its state on disk and
  applies the same rules Dodo documents, so read-back is real within the fixture.

SDK retries are off (`max_retries=0`). The SDK would otherwise retry a POST on a timeout or a 5xx, and Dodo takes
no idempotency header, so a retry could write twice. Retries belong to the rail, which reconciles first (§8).
"""

from __future__ import annotations

from typing import Any

import httpx
from dodopayments import (
    APIConnectionError,
    APIStatusError,
    AsyncDodoPayments,
    DodoPaymentsError,
    NotFoundError,
)

from contextrail.connectors.base import ConnectorError, TransientError, UnknownOutcome, WriteResult
from contextrail.connectors.state import FixtureState
from contextrail.models import Action
from contextrail.settings import Settings

ENVIRONMENT = "test_mode"
TEST_BASE_URL = "https://test.dodopayments.com"
_METADATA_MAX_PAIRS = 50  # Dodo usage-event metadata limits (usage-events docs, SDK EventInput)


def _map(e: Exception, what: str, *, write: bool) -> ConnectorError:
    """Dodo/SDK errors -> the connector contract. A lost connection on a write is an unknown outcome."""
    if isinstance(e, APIConnectionError):  # includes APITimeoutError
        return (UnknownOutcome if write else TransientError)(f"dodo: {what}: {type(e).__name__}")
    if isinstance(e, APIStatusError):
        status = e.status_code
        cls = TransientError if status in (408, 429) or status >= 500 else ConnectorError
        return cls(f"dodo: {what}: HTTP {status}")
    return ConnectorError(f"dodo: {what}: {type(e).__name__}")


class DodoTestMode:
    """LIVE against Dodo's test environment. Every call goes through the official SDK."""

    name = "dodo"
    mode = "LIVE"
    environment = ENVIRONMENT
    label = "LIVE · test mode"

    def __init__(self, api_key: str, *, http_client: httpx.AsyncClient | None = None,
                 pilot_customer_id: str = "", pilot_product_id: str = "") -> None:
        if not api_key:
            raise ValueError("DodoTestMode needs an API key; without one use FixtureDodo")
        # environment + base_url=None: the SDK then ignores DODO_PAYMENTS_BASE_URL (dodopayments/_client.py).
        self.client = AsyncDodoPayments(bearer_token=api_key, environment=ENVIRONMENT, base_url=None,
                                        max_retries=0, http_client=http_client)
        self.pilot_customer_id, self.pilot_product_id = pilot_customer_id, pilot_product_id

    def __repr__(self) -> str:
        return f"DodoTestMode(base_url={TEST_BASE_URL!r})"

    async def ingest_usage(self, events: list[dict]) -> int:
        try:
            return (await self.client.usage_events.ingest(events=events)).ingested_count
        except DodoPaymentsError as e:  # every SDK failure is mapped onto the connector contract
            raise _map(e, "ingest usage events", write=True) from e

    async def get_usage_event(self, event_id: str) -> dict | None:
        try:
            return (await self.client.usage_events.retrieve(event_id)).model_dump(mode="json")
        except NotFoundError:
            return None
        except DodoPaymentsError as e:
            raise _map(e, f"read usage event {event_id}", write=False) from e

    async def create_checkout(self, *, product_id: str, return_url: str | None = None,
                              customer: dict | None = None, metadata: dict | None = None) -> dict:
        kw: dict[str, Any] = {"product_cart": [{"product_id": product_id, "quantity": 1}]}
        for k, v in (("return_url", return_url), ("customer", customer), ("metadata", metadata)):
            if v:
                kw[k] = v
        try:
            r = await self.client.checkout_sessions.create(**kw)
        except DodoPaymentsError as e:
            raise _map(e, "create checkout session", write=True) from e
        return {"session_id": r.session_id, "checkout_url": r.checkout_url}

    # --- the rail's connector contract (refunds arrive with T207) ------------------------------------------------

    async def read(self, ref: dict) -> dict:
        if "event_id" in ref:
            return await self.get_usage_event(ref["event_id"]) or {}
        raise ConnectorError(f"dodo: cannot read {sorted(ref)}")

    async def write(self, action: Action, idem_key: str) -> WriteResult:
        raise ConnectorError(f"dodo: unsupported action kind {action.kind}")

    async def verify(self, action: Action) -> tuple[bool, dict]:
        raise ConnectorError(f"dodo: unsupported action kind {action.kind}")


class FixtureDodo:
    """FIXTURE stand-in with Dodo's documented behaviour: event_id dedupe, batch rules, metadata limits."""

    name = "dodo"
    mode = "FIXTURE"
    environment = "fixture"
    label = "FIXTURE"

    def __init__(self, state: FixtureState | None = None) -> None:
        self.state = state or FixtureState("dodo_payments")

    @property
    def pilot_customer_id(self) -> str:
        return self.state.load()["pilot"]["customer_id"]

    @property
    def pilot_product_id(self) -> str:
        return self.state.load()["pilot"]["product_id"]

    async def ingest_usage(self, events: list[dict]) -> int:
        ids = [e["event_id"] for e in events]
        if len(ids) != len(set(ids)):
            raise ConnectorError("dodo: duplicate event_id in one request; Dodo rejects the whole batch")
        for e in events:
            meta = e.get("metadata") or {}
            if len(meta) > _METADATA_MAX_PAIRS or any(isinstance(v, (dict, list)) for v in meta.values()):
                raise ConnectorError(f"dodo: event {e['event_id']} metadata must be at most 50 scalar pairs")

        def apply(doc: dict) -> int:
            new = 0
            for e in events:
                if e["event_id"] not in doc["events"]:  # an id already ingested is ignored, as in Dodo
                    doc["events"][e["event_id"]] = {"business_id": "bus_fx_northbeam", **e}
                    new += 1
            return new

        return await self.state.mutate(apply)

    async def get_usage_event(self, event_id: str) -> dict | None:
        ev = self.state.load()["events"].get(event_id)
        return dict(ev) if ev else None

    async def create_checkout(self, *, product_id: str, return_url: str | None = None,
                              customer: dict | None = None, metadata: dict | None = None) -> dict:
        def apply(doc: dict) -> str:
            sid = f"cks_fx_{len(doc['checkouts']) + 1:04d}"
            doc["checkouts"][sid] = {"product_id": product_id, "return_url": return_url, "customer": customer,
                                     "metadata": metadata}
            return sid

        sid = await self.state.mutate(apply)
        return {"session_id": sid, "checkout_url": f"fixture://dodo/checkouts/{sid}"}

    async def read(self, ref: dict) -> dict:
        if "event_id" in ref:
            return await self.get_usage_event(ref["event_id"]) or {}
        raise ConnectorError(f"dodo: cannot read {sorted(ref)}")

    async def write(self, action: Action, idem_key: str) -> WriteResult:
        raise ConnectorError(f"dodo: unsupported action kind {action.kind}")

    async def verify(self, action: Action) -> tuple[bool, dict]:
        raise ConnectorError(f"dodo: unsupported action kind {action.kind}")


def build_dodo(settings: Settings | None, *, state: FixtureState | None = None,
               http_client: httpx.AsyncClient | None = None) -> DodoTestMode | FixtureDodo:
    """LIVE (test mode) only when settings carry a DODO_API_KEY. No settings means FIXTURE: tests and tools never
    reach Dodo because a key happens to be in the environment."""
    if settings is not None and settings.dodo_configured:
        return DodoTestMode(settings.dodo_api_key.get_secret_value(), http_client=http_client,
                            pilot_customer_id=settings.dodo_customer_id, pilot_product_id=settings.dodo_product_id)
    return FixtureDodo(state)

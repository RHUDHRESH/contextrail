"""Dodo Payments (CLAUDE.md §14, checklist T206/T207): usage billing, the pilot checkout and refunds, TEST MODE ONLY.

Two connectors with one interface, both honest about what they are (D-004):
- `DodoTestMode` (mode LIVE) calls Dodo through the official `dodopayments` SDK, pinned to
  https://test.dodopayments.com. There is no setting that selects live mode, and the SDK's DODO_PAYMENTS_BASE_URL
  override is ignored. Its label always says "test mode".
- `FixtureDodo` (mode FIXTURE) is used whenever no DODO_API_KEY is configured. It keeps its state on disk and
  applies the same rules Dodo documents, so read-back is real within the fixture.

SDK retries are off (`max_retries=0`). The SDK would otherwise retry a POST on a timeout or a 5xx, and Dodo takes
no idempotency header, so a retry could write twice. Retries belong to the rail, which reconciles first (§8).

Refunds (T207). Dodo's POST /refunds takes no idempotency key, so ours travels in the refund's metadata
(`contextrail_idempotency_key`), and `write()` looks for it on the payment's refunds before it creates anything.
`verify()` finds the refund by that key and reads it back: only `succeeded` with the intended amount and currency is
verified. `pending` or `review` is read again a few times, then reported as not verified, never assumed.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import httpx
from dodopayments import (
    APIConnectionError,
    APIStatusError,
    AsyncDodoPayments,
    DodoPaymentsError,
    NotFoundError,
)

from contextrail.canonical import idempotency_key
from contextrail.connectors.base import ConnectorError, TransientError, UnknownOutcome, WriteResult
from contextrail.connectors.fixture import _apply
from contextrail.connectors.state import FixtureState
from contextrail.models import Action
from contextrail.settings import Settings

ENVIRONMENT = "test_mode"
TEST_BASE_URL = "https://test.dodopayments.com"
IDEMPOTENCY_METADATA = "contextrail_idempotency_key"
_METADATA_MAX_PAIRS = 50  # Dodo usage-event metadata limits (usage-events docs, SDK EventInput)
_PAGE_SIZE, _MAX_PAGES = 100, 20
_UNSETTLED = {"pending", "review"}
_REFUND_FIELDS = ("run_id", "payment_id", "amount_minor", "currency")


def _map(e: Exception, what: str, *, write: bool) -> ConnectorError:
    """Dodo/SDK errors -> the connector contract. A lost connection on a write is an unknown outcome."""
    if isinstance(e, APIConnectionError):  # includes APITimeoutError
        return (UnknownOutcome if write else TransientError)(f"dodo: {what}: {type(e).__name__}")
    if isinstance(e, APIStatusError):
        status = e.status_code
        cls = TransientError if status in (408, 429) or status >= 500 else ConnectorError
        return cls(f"dodo: {what}: HTTP {status}")
    return ConnectorError(f"dodo: {what}: {type(e).__name__}")


def _refund_target(action: Action) -> dict:
    if action.kind != "refund":
        raise ConnectorError(f"dodo: unsupported action kind {action.kind}")
    missing = [k for k in _REFUND_FIELDS if action.target.get(k) in (None, "")]
    if missing:
        raise ConnectorError(f"dodo: refund target missing {missing}")
    return action.target


def refund_key(action: Action) -> str:
    """The idempotency key execute used for this refund: the run id travels in the target for read-back."""
    return idempotency_key(action.target["run_id"], action.id, action.params_hash)


def _metadata(action: Action, key: str) -> dict:
    t = action.target
    meta = {IDEMPOTENCY_METADATA: key, "contextrail_run_id": str(t["run_id"]), "contextrail_action_id": action.id}
    meta.update({k: str(t[k]) for k in ("promise_ref", "credit_type", "quarter", "incident_id") if t.get(k)})
    return meta


def _reason(t: dict) -> str:
    what = f"{t.get('credit_type', 'service')} credit"
    refs = ", ".join(str(t[k]) for k in ("promise_ref", "incident_id") if t.get(k))
    return f"{what.capitalize()}{f' ({refs})' if refs else ''}, ContextRail run {str(t['run_id'])[:8]}"


def _observed(refund: dict | None, payment_id: str) -> dict:
    if refund is None:
        return {"refund_id": None, "status": "absent", "payment_id": payment_id}
    return {k: refund.get(k) for k in ("refund_id", "status", "amount", "currency", "payment_id")}


def _matches(refund: dict | None, t: dict) -> bool:
    return bool(refund) and refund["status"] == "succeeded" and refund.get("amount") == t["amount_minor"] \
        and refund.get("currency") == t["currency"]


def _find(payment: dict, key: str) -> dict | None:
    return next((r for r in payment["refunds"] if (r.get("metadata") or {}).get(IDEMPOTENCY_METADATA) == key), None)


class DodoTestMode:
    """LIVE against Dodo's test environment. Every call goes through the official SDK."""

    name = "dodo"
    mode = "LIVE"
    environment = ENVIRONMENT
    label = "LIVE · test mode"

    def __init__(self, api_key: str, *, http_client: httpx.AsyncClient | None = None,
                 pilot_customer_id: str = "", pilot_product_id: str = "", verify_reads: int = 3,
                 verify_interval_s: float = 1.0,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
        if not api_key:
            raise ValueError("DodoTestMode needs an API key; without one use FixtureDodo")
        # environment + base_url=None: the SDK then ignores DODO_PAYMENTS_BASE_URL (dodopayments/_client.py).
        self.client = AsyncDodoPayments(bearer_token=api_key, environment=ENVIRONMENT, base_url=None,
                                        max_retries=0, http_client=http_client)
        self.pilot_customer_id, self.pilot_product_id = pilot_customer_id, pilot_product_id
        self.verify_reads, self.verify_interval_s, self._sleep = verify_reads, verify_interval_s, sleep

    def __repr__(self) -> str:
        return f"DodoTestMode(base_url={TEST_BASE_URL!r})"

    # --- usage events and checkout (T206) ------------------------------------------------------------------------

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

    # --- payments and refunds (T207) -----------------------------------------------------------------------------

    async def payment(self, payment_id: str) -> dict:
        """One payment with every refund on it, each read in full (metadata is only on the refund itself)."""
        try:
            p = await self.client.payments.retrieve(payment_id)
            refunds = [(await self.client.refunds.retrieve(r.refund_id)).model_dump(mode="json") for r in p.refunds]
        except DodoPaymentsError as e:
            raise _map(e, f"read payment {payment_id}", write=False) from e
        return {"payment_id": p.payment_id, "customer_id": p.customer.customer_id, "status": p.status,
                "total_amount": p.total_amount, "currency": p.currency, "created_at": p.created_at.isoformat(),
                "product_cart": [c.model_dump(mode="json") for c in p.product_cart or []], "refunds": refunds}

    async def customer_payments(self, customer_id: str) -> list[dict]:
        ids: list[str] = []
        for page in range(_MAX_PAGES):  # page_number is 0-based in Dodo's docs; paged explicitly
            try:
                resp = await self.client.payments.list(customer_id=customer_id, page_size=_PAGE_SIZE,
                                                       page_number=page)
            except DodoPaymentsError as e:
                raise _map(e, f"list payments of {customer_id}", write=False) from e
            ids += [p.payment_id for p in resp.items]
            if len(resp.items) < _PAGE_SIZE:
                break
        return [await self.payment(pid) for pid in ids]

    async def read(self, ref: dict) -> dict:
        if "event_id" in ref:
            return await self.get_usage_event(ref["event_id"]) or {}
        if "payment_id" in ref:
            return await self.payment(ref["payment_id"])
        raise ConnectorError(f"dodo: cannot read {sorted(ref)}")

    async def write(self, action: Action, idem_key: str) -> WriteResult:
        t = _refund_target(action)
        payment = await self.payment(t["payment_id"])
        if (existing := _find(payment, idem_key)) is not None:  # reconcile first: Dodo cannot deduplicate for us
            return WriteResult(ok=True, replayed=True, ref=_observed(existing, t["payment_id"]), mode=self.mode)
        kw: dict[str, Any] = {"payment_id": t["payment_id"], "reason": _reason(t), "metadata": _metadata(action,
                                                                                                       idem_key)}
        if t["amount_minor"] != payment["total_amount"]:
            if not t.get("item_id"):
                raise ConnectorError("dodo: a partial refund needs the payment's item_id")
            kw["items"] = [{"item_id": t["item_id"], "amount": t["amount_minor"]}]
        try:
            r = await self.client.refunds.create(**kw)
        except DodoPaymentsError as e:
            raise _map(e, f"refund {t['payment_id']}", write=True) from e
        return WriteResult(ok=True, ref=_observed(r.model_dump(mode="json"), t["payment_id"]), mode=self.mode)

    async def verify(self, action: Action) -> tuple[bool, dict]:
        t = _refund_target(action)
        key = refund_key(action)
        for attempt in range(1, self.verify_reads + 1):
            refund = _find(await self.payment(t["payment_id"]), key)
            if refund is not None and refund["status"] in _UNSETTLED and attempt < self.verify_reads:
                await self._sleep(self.verify_interval_s)
                continue
            return _matches(refund, t), _observed(refund, t["payment_id"])
        raise AssertionError("unreachable")


class FixtureDodo:
    """FIXTURE stand-in with Dodo's documented behaviour: event_id dedupe, batch rules, metadata limits, refunds."""

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

    # --- payments and refunds (T207) -----------------------------------------------------------------------------

    @staticmethod
    def _payment(doc: dict, payment_id: str) -> dict:
        p = doc["payments"].get(payment_id)
        if p is None:
            raise ConnectorError(f"dodo: no payment {payment_id}")
        refunds = sorted((dict(r) for r in doc["refunds"].values() if r["payment_id"] == payment_id),
                         key=lambda r: r["created_at"])
        return {**p, "refunds": refunds}

    async def payment(self, payment_id: str) -> dict:
        return self._payment(self.state.load(), payment_id)

    async def customer_payments(self, customer_id: str) -> list[dict]:
        doc = self.state.load()
        return [self._payment(doc, pid) for pid, p in sorted(doc["payments"].items())
                if p["customer_id"] == customer_id]

    async def read(self, ref: dict) -> dict:
        if "event_id" in ref:
            return await self.get_usage_event(ref["event_id"]) or {}
        if "payment_id" in ref:
            return await self.payment(ref["payment_id"])
        raise ConnectorError(f"dodo: cannot read {sorted(ref)}")

    async def write(self, action: Action, idem_key: str) -> WriteResult:
        t = _refund_target(action)
        refund_id = f"ref_fx_{idem_key[:12]}"

        def apply(doc: dict) -> None:
            p = self._payment(doc, t["payment_id"])
            if p["status"] != "succeeded":
                raise ConnectorError(f"dodo: payment {p['payment_id']} is {p['status']}, not succeeded")
            left = p["total_amount"] - sum(r["amount"] for r in p["refunds"] if r["status"] != "failed")
            if t["amount_minor"] > left:
                raise ConnectorError(f"dodo: refund of {t['amount_minor']} exceeds the {left} left on "
                                     f"{p['payment_id']}")
            doc["refunds"][refund_id] = {
                "refund_id": refund_id, "payment_id": p["payment_id"], "customer_id": p["customer_id"],
                "amount": t["amount_minor"], "currency": t["currency"], "status": "succeeded",
                "is_partial": t["amount_minor"] != p["total_amount"], "reason": _reason(t),
                "created_at": datetime.now(UTC).isoformat(), "metadata": _metadata(action, idem_key)}

        return await _apply(self.state, t["payment_id"], idem_key,
                            {"refund_id": refund_id, "payment_id": t["payment_id"]}, apply)

    async def verify(self, action: Action) -> tuple[bool, dict]:
        t = _refund_target(action)
        refund = _find(await self.payment(t["payment_id"]), refund_key(action))
        return _matches(refund, t), _observed(refund, t["payment_id"])


def build_dodo(settings: Settings | None, *, state: FixtureState | None = None,
               http_client: httpx.AsyncClient | None = None) -> DodoTestMode | FixtureDodo:
    """LIVE (test mode) only when settings carry a DODO_API_KEY. No settings means FIXTURE: tests and tools never
    reach Dodo because a key happens to be in the environment."""
    if settings is not None and settings.dodo_configured:
        return DodoTestMode(settings.dodo_api_key.get_secret_value(), http_client=http_client,
                            pilot_customer_id=settings.dodo_customer_id, pilot_product_id=settings.dodo_product_id)
    return FixtureDodo(state)

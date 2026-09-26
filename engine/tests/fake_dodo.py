"""An in-memory stand-in for Dodo Payments' test API, mounted under the real SDK with httpx.MockTransport.

The engine's LIVE (test mode) connector is exercised through the official `dodopayments` SDK, so these tests check
the exact paths, methods and bodies the SDK sends. Only the network is replaced. Shapes follow the SDK types
(dodopayments/types: Event, UsageEventIngestResponse, CheckoutSessionResponse, Payment, Refund).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx

TEST_HOST = "test.dodopayments.com"


class FakeDodo:
    def __init__(self) -> None:
        self.events: dict[str, dict] = {}
        self.payments: dict[str, dict] = {}
        self.refunds: dict[str, dict] = {}
        self.requests: list[httpx.Request] = []
        self.fail_next: dict[str, int | str] = {}   # "METHOD /path-prefix" -> status code or "timeout"
        self.refund_status = "succeeded"            # status a new refund is created with

    # --- helpers for tests -------------------------------------------------------------------------------------

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handle))

    def bodies(self, method: str, path: str) -> list[dict]:
        return [json.loads(r.content) for r in self.requests if r.method == method and r.url.path == path]

    def add_payment(self, payment_id: str, *, customer_id: str, total: int, status: str = "succeeded",
                    product_id: str = "pdt_platform", currency: str = "USD") -> None:
        self.payments[payment_id] = {
            "payment_id": payment_id, "status": status, "total_amount": total, "currency": currency,
            "customer": {"customer_id": customer_id, "email": f"{customer_id}@example.com", "name": customer_id},
            "product_cart": [{"product_id": product_id, "quantity": 1}], "refunds": [],
            "brand_id": "bra_test", "business_id": "bus_test", "created_at": "2026-09-01T10:00:00Z",
            "billing": {"country": "IN"}, "digital_products_delivered": False, "disputes": [],
            "is_multi_subscription": False, "is_update_payment_method": False, "metadata": {},
            "payment_provider": "dodo", "retry_attempt": 0, "settlement_amount": total,
            "settlement_currency": currency, "subscription_ids": []}

    # --- the fake API ------------------------------------------------------------------------------------------

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.url.host == TEST_HOST, f"left test mode: {request.url}"
        for key, fault in list(self.fail_next.items()):
            method, prefix = key.split(" ", 1)
            if request.method == method and request.url.path.startswith(prefix):
                del self.fail_next[key]
                if fault == "timeout":
                    raise httpx.ReadTimeout("injected timeout", request=request)
                return httpx.Response(int(fault), json={"message": "injected"})
        path, method = request.url.path, request.method
        if method == "POST" and path == "/events/ingest":
            return self._ingest(json.loads(request.content))
        if method == "GET" and path.startswith("/events/"):
            ev = self.events.get(path.removeprefix("/events/"))
            return httpx.Response(200, json=ev) if ev else httpx.Response(404, json={"message": "not found"})
        if method == "POST" and path == "/checkouts":
            sid = f"cks_test_{len(self.requests)}"
            return httpx.Response(200, json={"session_id": sid,
                                             "checkout_url": f"https://test.checkout.dodopayments.com/{sid}"})
        if method == "GET" and path.startswith("/payments/"):
            p = self.payments.get(path.removeprefix("/payments/"))
            return httpx.Response(200, json=p) if p else httpx.Response(404, json={"message": "not found"})
        if method == "POST" and path == "/refunds":
            return self._refund(json.loads(request.content))
        if method == "GET" and path.startswith("/refunds/"):
            r = self.refunds.get(path.removeprefix("/refunds/"))
            return httpx.Response(200, json=r) if r else httpx.Response(404, json={"message": "not found"})
        return httpx.Response(404, json={"message": f"no route {method} {path}"})

    def _ingest(self, body: dict) -> httpx.Response:
        ids = [e["event_id"] for e in body["events"]]
        if len(ids) != len(set(ids)):
            return httpx.Response(422, json={"message": "duplicate event_id in request"})
        new = 0
        for e in body["events"]:
            if e["event_id"] in self.events:
                continue  # documented: an event_id already ingested is ignored
            self.events[e["event_id"]] = {"business_id": "bus_test", "customer_id": e["customer_id"],
                                          "event_id": e["event_id"], "event_name": e["event_name"],
                                          "timestamp": e.get("timestamp") or datetime.now(UTC).isoformat(),
                                          "metadata": e.get("metadata")}
            new += 1
        return httpx.Response(200, json={"ingested_count": new})

    def _refund(self, body: dict) -> httpx.Response:
        p = self.payments.get(body["payment_id"])
        if p is None:
            return httpx.Response(404, json={"message": "payment not found"})
        items = body.get("items") or []
        amount = sum(i["amount"] for i in items) if items else p["total_amount"]
        rid = f"ref_test_{len(self.refunds) + 1}"
        refund = {"refund_id": rid, "payment_id": p["payment_id"], "amount": amount, "currency": p["currency"],
                  "status": self.refund_status, "is_partial": bool(items), "reason": body.get("reason"),
                  "metadata": body.get("metadata") or {}, "customer": p["customer"], "brand_id": "bra_test",
                  "business_id": "bus_test", "created_at": datetime.now(UTC).isoformat()}
        self.refunds[rid] = refund
        p["refunds"].append({k: refund[k] for k in ("refund_id", "payment_id", "amount", "currency", "status",
                                                     "is_partial", "reason", "business_id", "created_at")})
        return httpx.Response(200, json=refund)

"""An in-memory stand-in for the engine's HTTP door (/v1), served through httpx.MockTransport.

It mirrors the shapes of engine/contextrail/surfaces/rest.py on sec/P-platform (runs, decisions) and the calls the
voice door defines for queries, caller identity and pending approvals (voice/README.md, "Engine API"). It decides
nothing interesting: tests set the answers they expect the engine to give, and assert what the voice door sent.
"""

from __future__ import annotations

import json
import uuid

import httpx

TOKEN = "test-engine-token"
HASH_A, HASH_B, HASH_C = "a" * 64, "b" * 64, "c" * 64

PEOPLE = {  # identity_map.phone -> person (fictional numbers from fixtures/identity.json)
    "+919990000142": {"person_id": "p-anil", "display_name": "Anil Kumar"},
    "+919990000150": {"person_id": "p-dana", "display_name": "Dana Osei"},
    "+919990000301": {"person_id": "p-meera", "display_name": "Meera Iyer"},
}


def row(action_id: str, *, label: str, verdict: str = "HOLD", state: str = "awaiting", rule_id: str = "POL-ACC-005",
        clause: str = "Paid SaaS seats need the manager's approval.", approver_id: str | None = "p-dana",
        approver_name: str | None = "Dana Osei", params_hash: str = HASH_A) -> dict:
    return {"action_id": action_id, "kind": "grant", "label": label, "verdict": verdict,
            "lamp": {"ALLOW": "✅", "HOLD": "🟠", "REFUSE": "⛔"}[verdict], "state": state, "rule_id": rule_id,
            "clause": clause, "approver_id": approver_id, "approver_name": approver_name, "explanation": None,
            "explainer": None, "verified": state == "verified", "params_hash": params_hash,
            "struck_through": verdict == "REFUSE", "connector_mode": "FIXTURE"}


def run_view(run_id: str | None = None, *, status: str = "awaiting_approval", request_text: str = "same as Rahul",
             rows: list[dict] | None = None, subject: str | None = "Anil Kumar") -> dict:
    rows = rows if rows is not None else []
    counts = {"allow": 0, "hold": 0, "refuse": 0, "verified": 0, "awaiting": 0, "failed": 0}
    for r in rows:
        counts[r["verdict"].lower()] += 1
        counts["verified"] += r["state"] == "verified"
        counts["awaiting"] += r["state"] == "awaiting"
    return {"run_id": run_id or str(uuid.uuid4()), "status": status, "stage": "approve", "source": "voice",
            "request_text": request_text, "subject": subject, "peer": "Rahul Mehta", "rows": rows,
            "counts": counts, "capsule_digest": "d" * 64, "modes": {"entitlements": "FIXTURE"}, "replay": False,
            "needs": []}


class FakeEngine:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.runs: dict[str, dict] = {}
        self.pending: dict[str, list[dict]] = {}   # person_id -> RunViews with rows awaiting them
        self.answer = {"text": "Your request is awaiting approval.", "run_id": None, "citations": [12, 14]}
        self.decision = {"outcome": "recorded", "reason": None, "rule_id": None, "decided_by": "p-dana",
                         "decided_channel": "voice", "view": None}
        self.fail_with: int | None = None

    def body(self, i: int = -1) -> dict:
        return json.loads(self.requests[i].content)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.headers.get("authorization") != f"Bearer {TOKEN}":
            return httpx.Response(401, json={"detail": "missing or invalid bearer token"})
        if self.fail_with:
            return httpx.Response(self.fail_with, json={"detail": "engine says no"})
        path, method = request.url.path, request.method
        body = json.loads(request.content) if request.content else {}
        if (method, path) == ("POST", "/v1/runs"):
            view = run_view(request_text=body["request_text"])
            self.runs[view["run_id"]] = view
            return httpx.Response(201, json=view, headers={"Location": f"/v1/runs/{view['run_id']}"})
        if method == "GET" and path.startswith("/v1/runs/"):
            rid = path.rsplit("/", 1)[1]
            if rid not in self.runs:
                return httpx.Response(404, json={"detail": f"no run {rid}"})
            return httpx.Response(200, json=self.runs[rid])
        if method == "POST" and path.startswith("/v1/runs/") and path.endswith("/decisions"):
            return httpx.Response(200, json=self.decision)
        if (method, path) == ("POST", "/v1/queries"):
            return httpx.Response(200, json=self.answer)
        if (method, path) == ("POST", "/v1/identities/resolve"):
            person = PEOPLE.get(body["external_id"]) if body["channel"] == "voice" else None
            return httpx.Response(200, json=person) if person else httpx.Response(404, json={"detail": "unknown"})
        if (method, path) == ("POST", "/v1/approvals/pending"):
            person = PEOPLE.get(body["actor_external_id"])
            runs = self.pending.get(person["person_id"], []) if person else []
            return httpx.Response(200, json={"runs": runs})
        return httpx.Response(404, json={"detail": "no route"})

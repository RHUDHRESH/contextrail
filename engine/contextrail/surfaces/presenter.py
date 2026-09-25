"""RunView: the one view every door renders (checklist T108, CLAUDE.md §13.0).

Slack Block Kit, the Teams Adaptive Card, the approval email, the voice script, the FDK sidebar and the MCP tools
all render from this object and nothing else, so they cannot disagree about a verdict (X6, D-005).
The view carries the lamps, the deciding rule and clause verbatim, the named approver, the explanation and who
wrote it, and the honest mode of every connector involved.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

LAMP = {"ALLOW": "✅", "HOLD": "🟠", "REFUSE": "⛔"}
Lamp = Literal["✅", "🟠", "⛔"]


class RowView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action_id: str
    kind: str
    label: str
    verdict: Literal["ALLOW", "HOLD", "REFUSE"]
    lamp: Lamp
    state: str
    rule_id: str
    clause: str
    approver_id: str | None = None
    approver_name: str | None = None
    explanation: str | None = None
    explainer: str | None = None
    verified: bool
    params_hash: str
    struck_through: bool  # refused rows stay visible, struck through (P4)
    connector_mode: str


class RunView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: UUID
    status: str
    stage: str | None
    source: str
    request_text: str
    subject: str | None
    peer: str | None
    rows: list[RowView]
    counts: dict[str, int]
    capsule_digest: str | None
    modes: dict[str, str]
    replay: bool = False
    needs: list[dict] = []


def _counts(rows: list[RowView]) -> dict[str, int]:
    out = {"allow": 0, "hold": 0, "refuse": 0, "verified": 0, "awaiting": 0, "failed": 0}
    for r in rows:
        out[r.verdict.lower()] += 1
        out["verified"] += r.state == "verified"
        out["awaiting"] += r.state == "awaiting"
        out["failed"] += r.state in ("failed", "unknown")
    return out


def build_view(run: dict, actions: list[dict], *, people: dict[str, str], modes: dict[str, str],
               needs: list[dict] | None = None) -> RunView:
    """Pure function of stored state: the same inputs always give the same view, whichever door asks."""
    capsule = run.get("capsule") or {}
    decisions = {d["action_id"]: d for d in capsule.get("decisions", [])}
    order = [a["id"] for a in capsule.get("actions", [])] or [a["id"] for a in actions]
    by_id = {a["id"]: a for a in actions}
    rows = []
    for aid in order:
        a = by_id.get(aid)
        if a is None:
            continue
        t = a["target"]
        connector = "github" if t.get("system") == "github" else "entitlements"
        d = decisions.get(aid, {})
        rows.append(RowView(
            action_id=aid, kind=a["kind"], label=t.get("label") or t.get("entitlement") or aid,
            verdict=a["verdict"], lamp=LAMP[a["verdict"]], state=a["state"], rule_id=a["rule_id"],
            clause=a["clause"], approver_id=a["approver"], approver_name=people.get(a["approver"] or ""),
            explanation=d.get("explanation"), explainer=d.get("explainer"), verified=a["state"] == "verified",
            params_hash=a["params_hash"], struck_through=a["verdict"] == "REFUSE",
            connector_mode=modes.get(connector, "unknown")))
    subject, peer = capsule.get("subject") or {}, capsule.get("peer") or {}
    return RunView(
        run_id=run["id"], status=run["status"], stage=run.get("stage"), source=run["source"],
        request_text=run["request_text"], subject=subject.get("display_name"), peer=peer.get("display_name"),
        rows=rows, counts=_counts(rows), capsule_digest=run.get("capsule_digest"),
        modes={k: modes[k] for k in sorted(modes)}, needs=needs or [])

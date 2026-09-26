"""The receipt as a read-only, printable page (checklist T215): GET /r/{run_id}?sig=<hmac>.

Rendered from the stored receipt (receipts table, T210), never rebuilt on view, so the page shows exactly what was
recorded, with its digest, seal and chain status. A person opens it from a link (ticket note, chat, email), where no
bearer header exists, so the link carries an HMAC over "receipt|<run_id>" keyed with DECISION_LINK_SECRET (the
"receipt|" prefix keeps it distinct from decision tokens). An unset or placeholder secret closes the page (503)
rather than minting links anyone could forge. GET only; nothing here changes state.

Everything is HTML-escaped: the request text is untrusted input (P6). The page sends no-store, no-referrer (the URL
holds the signature) and a CSP that allows no scripts at all.
"""

from __future__ import annotations

import hashlib
import hmac
from html import escape
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from contextrail.settings import Settings

router = APIRouter(tags=["receipts"])
_PLACEHOLDER = "change-me"
_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"}


def _secret(settings: Settings) -> str | None:
    s = settings.decision_link_secret.get_secret_value()
    return None if not s or s == _PLACEHOLDER else s


def _sig(secret: str, run_id: object) -> str:
    return hmac.new(secret.encode(), f"receipt|{run_id}".encode(), hashlib.sha256).hexdigest()


def receipt_url(settings: Settings, run_id: object) -> str:
    """The link doors put next to a receipt. Refuses to sign with an unset or placeholder secret."""
    secret = _secret(settings)
    if secret is None:
        raise ValueError("DECISION_LINK_SECRET is not configured; receipt links would be forgeable")
    return f"{settings.public_url}/r/{run_id}?sig={_sig(secret, run_id)}"


@router.get("/r/{run_id}", response_class=HTMLResponse)
async def receipt_page(run_id: UUID, request: Request, sig: str = "") -> HTMLResponse:
    platform = request.app.state.platform
    secret = _secret(platform.settings)
    if secret is None:
        raise HTTPException(503, "DECISION_LINK_SECRET is not configured; receipt pages stay closed until it is set")
    if not hmac.compare_digest(sig.encode(), _sig(secret, run_id).encode()):
        raise HTTPException(403, "this receipt link is not valid")
    async with platform.db.connection() as c:
        row = await (await c.execute("select summary, body from receipts where run_id = %s", (run_id,))).fetchone()
    if row is None:
        raise HTTPException(404, "no receipt for this run yet")
    return HTMLResponse(render(row["body"], row["summary"]), headers=_HEADERS)


def _e(value) -> str:
    return escape("" if value is None else str(value), quote=True)


def render(body: dict, summary: str) -> str:
    run, cap, audit, check = body["run"], body["capsule"], body["audit"], body["chain"]
    actions = []
    for a in body["actions"]:
        label = f"<s>{_e(a['label'])}</s>" if a["struck_through"] else _e(a["label"])
        actions.append(
            f"<tr class='{_e(a['verdict'].lower())}'><td>{_e(a['lamp'])}</td><td>{label}</td><td>{_e(a['verdict'])}"
            f"</td><td>{_e(a['rule_id'])}</td><td>&ldquo;{_e(a['clause'])}&rdquo;</td>"
            f"<td>{_e(a['approver_name'] or a['approver_id'])}</td><td>{_e(a['state'])}</td>"
            f"<td>{_e(a['verified_at'])}</td></tr>")
    labels = {a["action_id"]: a["label"] for a in body["actions"]}
    decisions = [f"<tr><td>{_e(labels.get(d['action_id'], d['action_id']))}</td><td>{_e(d['decision'])}</td>"
                 f"<td>{_e(d['approver_name'] or d['approver'])}</td><td>{_e(d['channel'])}</td>"
                 f"<td>{_e(d['decided_at'])}</td><td>{_e(d['reason'])}</td></tr>" for d in body["decisions"]]
    evidence = [f"<li>{_e(e['id'])} &middot; {_e(e['kind'])} &middot; {_e(e['trust'])}"
                f"{' &middot; stale' if e['stale'] else ''}</li>" for e in body["evidence"]]
    seal = {True: "seal verified", False: "seal BROKEN", None: "no case file"}[cap["seal_verified"]]
    chain = "chain intact" if check["ok"] else f"chain BROKEN at seq {_e(check['first_broken_seq'])}"
    modes = ", ".join(f"{_e(k)} {_e(v)}" for k, v in body["connectors"].items())
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>ContextRail receipt {_e(run['id'][:8])}</title>
<style>
body {{ font: 14px/1.45 system-ui, sans-serif; color: #111; margin: 24px auto; max-width: 1000px; padding: 0 16px; }}
table {{ border-collapse: collapse; width: 100%; margin: 8px 0 20px; }}
th, td {{ border-bottom: 1px solid #ccc; padding: 4px 6px; text-align: left; vertical-align: top; }}
pre {{ white-space: pre-wrap; background: #f4f4f4; padding: 10px; }}
.refuse td {{ color: #8a1c1c; }} .mono {{ font-family: ui-monospace, monospace; word-break: break-all; }}
@page {{ margin: 16mm; }}
@media print {{ body {{ margin: 0; max-width: none; }} pre {{ background: none; border: 1px solid #999; }} }}
</style></head><body>
<h1>ContextRail receipt</h1>
<p>Run <span class="mono">{_e(run['id'])}</span> &middot; <strong>{_e(run['status'])}</strong> &middot;
source {_e(run['source'])} {_e(run['source_ref'])} &middot; built {_e(body['built_at'])}</p>
<pre>{_e(summary)}</pre>
<h2>Actions</h2>
<table><tr><th></th><th>Action</th><th>Verdict</th><th>Rule</th><th>Clause</th><th>Approver</th><th>State</th>
<th>Verified at</th></tr>{''.join(actions)}</table>
<h2>Decisions</h2>
<table><tr><th>Action</th><th>Decision</th><th>By</th><th>Door</th><th>At</th><th>Reason</th></tr>{''.join(decisions)}
</table>
<h2>Evidence</h2><ul>{''.join(evidence)}</ul>
<h2>Integrity</h2>
<p>Case digest <span class="mono">{_e(cap['digest'])}</span> ({seal})<br>
Audit seq {_e(audit['from_seq'])}&ndash;{_e(audit['to_seq'])}, {_e(audit['events'])} events ({chain})<br>
Receipt digest <span class="mono">{_e(body['digest'])}</span><br>
Connectors: {modes}</p>
</body></html>"""

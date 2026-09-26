"""The decision page behind every email Approve/Refuse button: /a/{token} (CLAUDE.md §13.6, §23, D-007, T232).

GET only renders a confirm page. It reads the run, the action and any existing decision, and writes nothing: no
approval, no audit row, no job. Corporate link scanners prefetch every URL in an email, so a GET that decided would
approve things without a human.

POST verifies the token again (never trusting the GET) and hands the decision to door.decide(channel="email"),
with the approver's email from the identity map as the actor. The door applies identity, params_hash, separation of
duties and first-decision-wins, audits, and queues the Freshservice mirror and every other door's update. A link
that cannot be used (malformed, bad signature, expired) is rejected on POST and audited as
`decision_link.rejected` with what it claimed and a fingerprint, never the token itself.

The app must set `app.state.door` (a surfaces.door.Door); `app.state.settings.decision_link_secret` signs links.
"""

from __future__ import annotations

import hashlib
import html
from urllib.parse import parse_qs

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from contextrail import repo
from contextrail.audit import chain
from contextrail.logs import get_logger
from contextrail.surfaces.decision_link import LinkClaims, LinkError, LinkSigner, WeakSecret, format_ist
from contextrail.surfaces.door import DecisionResult, Door
from contextrail.surfaces.presenter import RowView, RunView

router = APIRouter(tags=["email"])
log = get_logger("contextrail.decision_page")

_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",            # the token is in the URL; never leak it to another site
    "X-Frame-Options": "DENY",                   # the confirm button must not be clickjacked
    "Content-Security-Policy": ("default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
                                "frame-ancestors 'none'; base-uri 'none'"),
    "X-Robots-Tag": "noindex, nofollow",
    "X-Content-Type-Options": "nosniff",
}
_LINK_ERRORS = {
    "malformed": (400, "This link is not valid", "It may have been cut short or altered."),
    "bad_signature": (400, "This link is not valid",
                      "It was not issued by ContextRail, or it was altered after it was sent."),
    "expired": (410, "This link has expired", "Ask for a new approval request if this still needs a decision."),
}
_VERB = {"approved": "approve", "refused": "refuse"}
_STYLE = ("body{font:16px/1.5 system-ui,sans-serif;margin:0;background:#f6f7f9;color:#1d2330}"
          "main{max-width:34rem;margin:0 auto;padding:1.5rem}h1{font-size:1.4rem}"
          "dt{font-weight:600;margin-top:.6rem}dd{margin:0}blockquote{margin:.2rem 0;padding-left:.7rem;"
          "border-left:3px solid #c9ced8}textarea{width:100%;box-sizing:border-box}"
          "button{font-size:1.05rem;padding:.7rem 1.4rem;margin-top:.8rem;border:0;border-radius:6px;"
          "background:#1d2330;color:#fff}.fine{color:#5b6475;font-size:.9rem}")


def _t(value: object) -> str:
    return html.escape(str(value), quote=False)


def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    doc = (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
           f'<meta name="viewport" content="width=device-width, initial-scale=1">'
           f'<meta name="robots" content="noindex,nofollow"><title>ContextRail · {_t(title)}</title>'
           f"<style>{_STYLE}</style></head><body><main>{body}</main></body></html>")
    return HTMLResponse(doc, status_code=status, headers=_HEADERS)


def _message(title: str, text: str, status: int) -> HTMLResponse:
    return _page(title, f"<h1>{_t(title)}</h1><p>{_t(text)}</p>", status)


def _signer(request: Request) -> LinkSigner | None:
    try:
        return LinkSigner(request.app.state.settings.decision_link_secret)
    except WeakSecret:
        return None


def _door(request: Request) -> Door | None:
    return getattr(request.app.state, "door", None)


def _unavailable(signer: LinkSigner | None) -> HTMLResponse:
    why = ("decision links are switched off until DECISION_LINK_SECRET is set to a strong value" if signer is None
           else "the engine is not ready to take decisions")
    return _message("Decisions are unavailable", f"Nothing was recorded: {why}. Please try again later.", 503)


def _action_details(view: RunView, row: RowView, claims: LinkClaims) -> str:
    who = f"{view.subject} (same as {view.peer})" if view.peer else (view.subject or "")
    items = [("Action", _t(row.label)), ("For", _t(who)), ("Request", f"“{_t(view.request_text)}”"),
             ("Rule", _t(row.rule_id)), ("Clause", f"<blockquote>{_t(row.clause)}</blockquote>")]
    if row.explanation:
        items.append(("Why it is held", f"{_t(row.explanation)} <span class=fine>({_t(row.explainer)})</span>"))
    items += [("System", f"{_t(row.connector_mode)}"), ("Link expires", _t(format_ist(claims.expires_at)))]
    return "<dl>" + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in items) + "</dl>"


@router.get("/a/{token}", response_class=HTMLResponse)
async def confirm_page(token: str, request: Request) -> HTMLResponse:
    """Read-only. Shows what the link would decide and asks for a confirming POST."""
    signer, door = _signer(request), _door(request)
    if signer is None or door is None:
        return _unavailable(signer)
    try:
        claims = signer.verify(token)
    except LinkError as e:
        log.warning("decision_link_unusable", reason=e.reason, method="GET")
        status, title, text = _LINK_ERRORS[e.reason]
        return _message(title, text, status)
    try:
        view = await door.get_status(claims.run_id)
    except LookupError:
        return _message("Request not found", "This request no longer exists.", 404)
    row = next((r for r in view.rows if r.action_id == claims.action_id), None)
    if row is None:
        return _message("Action not found", "This action is not part of the request.", 404)
    async with door.db.connection() as c:
        existing = await repo.get_approval(c, claims.run_id, claims.action_id)
    if existing:
        name = door.people.get(existing["approver"], existing["approver"])
        return _message("Already decided", f"This was already {existing['decision']} by {name} via "
                        f"{existing['channel']}. Nothing more is needed.", 409)
    if row.params_hash != claims.params_hash:
        return _message("This link is out of date", "The action's parameters changed after this email was sent, "
                        "so this link can no longer decide it.", 409)
    if row.approver_id != claims.approver:
        return _message("Not your decision", f"Only {row.approver_name or row.approver_id} can decide this.", 403)
    if row.state != "awaiting":
        return _message("Nothing to decide", f"This action is {row.state}, not waiting for a decision.", 409)
    verb = _VERB[claims.decision]
    name = door.people.get(claims.approver, claims.approver)
    body = (f"<h1>{_t(row.lamp)} Confirm: {verb}</h1>"
            f"<p>You are deciding as <strong>{_t(name)}</strong>, the named approver.</p>"
            f"{_action_details(view, row, claims)}"
            f'<form method="post"><label for="reason">Reason (optional)</label>'
            f'<textarea id="reason" name="reason" maxlength="500" rows="3"></textarea>'
            f'<button type="submit">Confirm: {verb}</button></form>'
            f"<p class=fine>Nothing has been decided yet. Opening this page changes nothing; only the button "
            f"records a decision. Run {_t(str(view.run_id)[:8])}.</p>")
    return _page(f"Confirm {verb}", body)


async def _approver_email(door: Door, person_id: str) -> str | None:
    async with door.db.connection() as c:
        row = await (await c.execute("select email from identity_map where person_id = %s", (person_id,))).fetchone()
    return row["email"] if row else None


async def _audit_unusable_link(door: Door, token: str, err: LinkError) -> None:
    claimed = err.claims
    async with door.db.transaction() as c:
        run_id = claimed.run_id if claimed and await repo.get_run(c, claimed.run_id) else None
        await chain.append(c, run_id=run_id, event="decision_link.rejected", payload={
            "reason": err.reason, "channel": "email",
            "claimed": ({"action_id": claimed.action_id, "approver": claimed.approver, "decision": claimed.decision,
                         "exp": claimed.exp} if claimed else None),
            "fingerprint": hashlib.sha256(token.encode()).hexdigest()[:16]})


async def _reason(request: Request) -> str | None:
    if not request.headers.get("content-type", "").startswith("application/x-www-form-urlencoded"):
        return None
    form = parse_qs((await request.body())[:4096].decode("utf-8", "replace"), max_num_fields=5)
    return (form.get("reason") or [""])[0].strip()[:500] or None


def _result_page(door: Door, claims: LinkClaims, result: DecisionResult) -> HTMLResponse:
    if result.outcome == "recorded":
        done = "Approved" if claims.decision == "approved" else "Refused"
        name = door.people.get(claims.approver, claims.approver)
        return _message(done, f"Recorded: {claims.decision} by {name} via email. Every other door now shows this "
                        "decision, and the request carries on.", 200)
    if result.outcome == "already_decided":
        name = door.people.get(result.decided_by or "", result.decided_by)
        return _message("Already decided", f"Nothing changed: this was {result.reason} by {name} via "
                        f"{result.decided_channel}.", 409)
    return _message("Not recorded", f"Nothing changed: {result.reason}.", 403)


@router.post("/a/{token}", response_class=HTMLResponse)
async def decide(token: str, request: Request) -> HTMLResponse:
    """The only way an email link decides: through the door contract, like every other door."""
    signer, door = _signer(request), _door(request)
    if signer is None or door is None:
        return _unavailable(signer)
    try:
        claims = signer.verify(token)
    except LinkError as e:
        log.warning("decision_link_rejected", reason=e.reason, method="POST")
        await _audit_unusable_link(door, token, e)
        status, title, text = _LINK_ERRORS[e.reason]
        return _message(title, f"Nothing was recorded. {text}", status)
    result = await door.decide(claims.run_id, claims.action_id, claims.params_hash, channel="email",
                               actor_external_id=await _approver_email(door, claims.approver),
                               decision=claims.decision, reason=await _reason(request))
    return _result_page(door, claims, result)

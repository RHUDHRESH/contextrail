"""Freshservice as the base (CLAUDE.md §13.2): native approvals for held actions, and mirrors of decisions.

Plain async job handlers for the worker. `ctx` is anything with `.db` (Database) and `.registry` (a Registry
holding "freshservice"), for example RailDeps.

- handle_fs_approval_request(payload, ctx) consumes 'approval.dispatch' {run_id, action_id, ...}, which
  rail/approve.py enqueues per held action. It asks the action's named approver for a Freshservice approval on the
  run's ticket, stores where it lives in door_messages (channel 'freshservice') and audits it (P0-4).
  `request_fs_approvals(ctx, run_id)` does the same for every held action of a run.
- handle_fs_approval_mirror(payload, ctx) consumes 'fs.approval.mirror' {run_id, action_id}, which door.decide
  enqueues. It writes the recorded decision onto the ticket. The Freshservice API can only cancel an approval,
  never approve or reject one (D-015), so the mirror is a private note, found by its marker before posting and
  read back after. The Freshservice approval's own state is reported alongside, and a disagreement is flagged:
  the first decision, recorded in `approvals`, stands (D-005).

A run's ticket is `runs.source_ref` when `runs.source` is 'freshservice' (the webhook path). Runs from other doors
have no ticket until catalog place_request lands (T131); their approvals are skipped here, and say so.
Approvers map to Freshservice users through identity_map.fs_agent_id, or else an exact agent email lookup; no
match (or several) blocks the request instead of guessing (P1). Every result carries the connector mode.
"""

from __future__ import annotations

import html
from datetime import UTC
from typing import Any, Protocol
from uuid import UUID

from psycopg import AsyncConnection

from contextrail import repo
from contextrail.audit import chain
from contextrail.canonical import door_send_key
from contextrail.connectors.base import ConnectorError, TransientError
from contextrail.connectors.freshservice import FreshserviceConnector, fs_id
from contextrail.db import Database
from contextrail.surfaces.presenter import RowView, build_view

CHANNEL = "freshservice"


class JobContext(Protocol):
    db: Database
    registry: Any


def _skip(run_id: UUID, action_id: str, reason: str) -> dict:
    return {"status": "skipped", "run_id": str(run_id), "action_id": action_id, "reason": reason}


def ticket_of(run: dict) -> int | None:
    if run.get("source") != "freshservice":
        return None
    try:
        return fs_id(run.get("source_ref"))
    except (ValueError, TypeError):
        return None


async def _one(conn: AsyncConnection, sql: str, *params: object) -> dict | None:
    return await (await conn.execute(sql, params)).fetchone()


async def _rows(ctx: JobContext, conn: AsyncConnection, run: dict) -> dict[str, RowView]:
    """The run's actions as every door sees them (label, rule, clause, approver name): from RunView, not re-derived."""
    people = {r["person_id"]: r["display_name"] for r in
              await (await conn.execute("select person_id, display_name from identity_map")).fetchall()}
    modes = {name: c.mode for name, c in ctx.registry.connectors.items()}
    view = build_view(run, await repo.list_actions(conn, run["id"]), people=people, modes=modes)
    return {r.action_id: r for r in view.rows}


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


# --- approvals for held actions --------------------------------------------------------------------------------

async def request_fs_approvals(ctx: JobContext, run_id: UUID) -> list[dict]:
    async with ctx.db.connection() as c:
        ids = [a["id"] for a in await repo.list_actions(c, run_id) if a["state"] == "awaiting"]
    return [await request_fs_approval(ctx, run_id, aid) for aid in ids]


async def handle_fs_approval_request(payload: dict, ctx: JobContext) -> dict:
    """Job handler for 'approval.dispatch'."""
    return await request_fs_approval(ctx, UUID(str(payload["run_id"])), payload["action_id"])


async def request_fs_approval(ctx: JobContext, run_id: UUID, action_id: str) -> dict:
    fs: FreshserviceConnector = ctx.registry.get("freshservice")
    async with ctx.db.connection() as c:
        run = await repo.get_run(c, run_id)
        action = await _one(c, "select * from actions where run_id = %s and id = %s", run_id, action_id)
        stored = await _one(c, "select ref from door_messages where run_id = %s and action_id = %s and channel = %s",
                            run_id, action_id, CHANNEL)
        if run is None or action is None:
            return _skip(run_id, action_id, "no such action")
        if action["state"] != "awaiting":
            return _skip(run_id, action_id, f"action is {action['state']}, not awaiting a decision")
        ticket_id = ticket_of(run)
        if ticket_id is None:
            return _skip(run_id, action_id, "the run has no Freshservice ticket")
        if stored and stored["ref"].get("approval_id"):
            return {"status": "exists", "run_id": str(run_id), "action_id": action_id, **stored["ref"]}
        person = await _one(c, "select * from identity_map where person_id = %s", action["approver"])
        waiting = [r for r in (await _rows(ctx, c, run)).values()
                   if r.state == "awaiting" and r.approver_id == action["approver"]]

    approver_id, why = await _fs_user(fs, action["approver"], person)
    if approver_id is None:
        async with ctx.db.transaction() as c:
            await chain.append(c, run_id=run_id, event="fs.approval.blocked",
                               payload={"action_id": action_id, "approver": action["approver"], "reason": why})
        return {"status": "blocked", "run_id": str(run_id), "action_id": action_id, "reason": why}

    got = await fs.request_approval(ticket_id, approver_id, email_content=_approval_email(run, waiting))
    ref = {"ticket_id": got.ticket_id, "approval_id": got.approval_id, "approver_id": got.approver_id,
           "approval_status": got.status, "replayed": got.replayed, "mode": got.mode,
           "fallback_reason": got.fallback_reason}
    async with ctx.db.transaction() as c:
        await repo.upsert_door_message(c, run_id, CHANNEL, ref, action_id=action_id)
        await chain.append(c, run_id=run_id, event="fs.approval.requested", payload={"action_id": action_id, **ref})
    return {"status": "requested", "run_id": str(run_id), "action_id": action_id, **ref}


async def _fs_user(fs: FreshserviceConnector, person_id: str, person: dict | None) -> tuple[int | None, str | None]:
    """The approver's Freshservice user id: the mapped id, else the one agent with exactly their email."""
    if person is None:
        return None, f"{person_id} is not in the identity map"
    if person.get("fs_agent_id"):
        return fs_id(person["fs_agent_id"]), None
    if not person.get("email"):
        return None, f"{person_id} has no email to find their Freshservice agent by"
    found = (await fs.find_agents_by_email(person["email"])).data
    if len(found) != 1:
        return None, f"{len(found)} Freshservice agents match {person_id}'s email; map fs_agent_id for {person_id}"
    return found[0]["id"], None


def _approval_email(run: dict, rows: list[RowView]) -> str:
    items = "".join(f"<li><b>{_e(r.label)}</b> ({_e(r.kind)}): {_e(r.rule_id)}, &ldquo;{_e(r.clause)}&rdquo;</li>"
                    for r in rows)
    return (f"<p>ContextRail asks for your approval on this request: {_e(run['request_text'])}</p><ul>{items}</ul>"
            f"<p>You can decide here, or in Slack, Teams or email; the first decision counts everywhere. "
            f"Run {_e(run['id'])}.</p>")


# --- mirroring a decision onto the ticket ----------------------------------------------------------------------

def mirror_marker(run_id: UUID, action_id: str) -> str:
    return "cr-mirror:" + door_send_key(run_id, action_id, CHANNEL)[:24]


async def handle_fs_approval_mirror(payload: dict, ctx: JobContext) -> dict:
    """Job handler for 'fs.approval.mirror'. Raises TransientError if the note cannot be read back, so the job
    is retried; the retry finds the note by its marker instead of posting a second one."""
    run_id, action_id = UUID(str(payload["run_id"])), payload["action_id"]
    fs: FreshserviceConnector = ctx.registry.get("freshservice")
    async with ctx.db.connection() as c:
        run = await repo.get_run(c, run_id)
        decision = await repo.get_approval(c, run_id, action_id)
        if run is None or decision is None:
            return _skip(run_id, action_id, "no decision recorded for this action")
        if decision["channel"] == CHANNEL:
            return _skip(run_id, action_id, "decided in Freshservice itself; nothing to mirror")
        stored = await _one(c, "select ref from door_messages where run_id = %s and action_id = %s and channel = %s",
                            run_id, action_id, CHANNEL)
        ref = dict(stored["ref"]) if stored else {}
        ticket_id = ref.get("ticket_id") or ticket_of(run)
        if ticket_id is None:
            return _skip(run_id, action_id, "the run has no Freshservice ticket")
        row = (await _rows(ctx, c, run)).get(action_id)
        who = await _one(c, "select display_name from identity_map where person_id = %s", decision["approver"])

    fs_state = None
    if ref.get("approval_id"):
        try:
            a = await fs.get_approval(ticket_id, ref["approval_id"])
            fs_state = {"approval_id": a.approval_id, "status": a.status, "mode": a.mode,
                        "fallback_reason": a.fallback_reason}
        except ConnectorError as e:  # the decision still gets mirrored; the unknown state is said out loud
            fs_state = {"approval_id": ref["approval_id"], "status": "unavailable", "error": str(e)}
    conflict = bool(fs_state and fs_state["status"] in ("approved", "rejected")
                    and (fs_state["status"] == "approved") != (decision["decision"] == "approved"))

    body = _mirror_note(run, decision, row, who["display_name"] if who else decision["approver"], fs_state, conflict)
    note = await fs.add_private_note(ticket_id, body, mirror_marker(run_id, action_id))
    if not note.confirmed:
        raise TransientError(f"mirror note {note.note_id} on ticket {ticket_id} is not visible on re-fetch")
    mirror = {"note_id": note.note_id, "confirmed": note.confirmed, "replayed": note.replayed, "mode": note.mode,
              "fallback_reason": note.fallback_reason, "fs_approval": fs_state, "conflict": conflict}
    async with ctx.db.transaction() as c:
        await repo.upsert_door_message(c, run_id, CHANNEL, {**ref, "ticket_id": ticket_id, "mirror": mirror},
                                       action_id=action_id)
        await chain.append(c, run_id=run_id, event="fs.approval.mirrored",
                           payload={"action_id": action_id, "decision": decision["decision"],
                                    "approver": decision["approver"], "channel": decision["channel"],
                                    "ticket_id": ticket_id, **mirror})
    return {"status": "mirrored", "run_id": str(run_id), "action_id": action_id, "ticket_id": ticket_id, **mirror}


def _mirror_note(run: dict, decision: dict, row: RowView | None, name: str, fs_state: dict | None,
                 conflict: bool) -> str:
    when = decision["decided_at"].astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
    what = f"{_e(row.label)} ({_e(row.kind)}), rule {_e(row.rule_id)}" if row else _e(decision["action_id"])
    parts = [(f"<p><b>ContextRail decision</b>: {what} was <b>{_e(decision['decision'])}</b> by {_e(name)} "
              f"via {_e(decision['channel'])} at {_e(when)}.</p>")]
    if decision.get("reason"):
        parts.append(f"<p>Reason given: {_e(decision['reason'])}</p>")
    parts.append(f"<p>Bound to parameters {_e(decision['params_hash'][:12])}. Run {_e(run['id'])}.</p>")
    if fs_state:
        parts.append(f"<p>Freshservice approval {_e(fs_state['approval_id'])} shows: {_e(fs_state['status'])}.</p>")
    if conflict:
        parts.append("<p>That differs from the decision above. The first decision recorded by any door stands.</p>")
    parts.append("<p>The Freshservice API cannot mark an approval approved or rejected, so this note is the "
                 "record of the decision on this ticket.</p>")
    return "".join(parts)

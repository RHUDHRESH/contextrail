"""One governed request plus its Freshservice ticket, shared by the web and messaging doors."""

from __future__ import annotations

from html import escape
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel

from contextrail import repo
from contextrail.connectors.base import ConnectorError, UnknownOutcome
from contextrail.connectors.freshservice import ACCESS_REQUEST_TEXT_FIELD, FreshserviceHTTPError, fs_id
from contextrail.intake import advisory_lock
from contextrail.settings import get_settings
from contextrail.surfaces.presenter import RunView


class VoiceTicket(BaseModel):
    status: Literal["attempted", "verified", "unverified", "unknown", "blocked"]
    ticket_id: int | None = None
    mode: Literal["LIVE", "FIXTURE"]


class VoiceRequestResult(BaseModel):
    run: RunView
    ticket: VoiceTicket


async def start_ticket_request(platform, *, request_text: str, actor_external_id: str, source_ref: str,
                               channel: str, source: str, ticket_tag: str | None = None,
                               idempotency_key: str | None = None
                               ) -> VoiceRequestResult:
    """Start or resume one request and create/read back at most one Freshservice ticket.

    `source_ref` identifies the visible originating message for the run. When a source retries with a new message
    reference, pass its stable `idempotency_key` (Slack's team + trigger id); the webhook ledger resolves it to the
    original run so neither the rail nor Freshservice writes a duplicate.
    """
    actor = await platform.door.resolve_actor(channel, actor_external_id)
    if actor is None or not actor.get("email"):
        raise HTTPException(403, "a registered requester with an email is required")
    lock_key = (f"{source}:event:{idempotency_key}" if idempotency_key else f"{source}:{source_ref}")
    async with advisory_lock(platform.db, lock_key) as c:
        existing = None
        if idempotency_key:
            dedupe = await (await c.execute(
                "select run_id from webhook_dedupe where source = %s and external_id = %s",
                (source, idempotency_key))).fetchone()
            if dedupe and dedupe["run_id"]:
                existing = await (await c.execute(
                    "select id, requested_by, request_text from runs where id = %s", (dedupe["run_id"],)
                )).fetchone()
        if existing is None:
            existing = await (await c.execute(
                "select id, requested_by, request_text from runs where source = %s and source_ref = %s "
                "order by created_at limit 1", (source, source_ref))).fetchone()
        if existing and (existing["requested_by"] != actor["person_id"] or
                         existing["request_text"] != request_text):
            raise HTTPException(409, "this request reference belongs to a different request")
        view = (await platform.door.get_status(existing["id"]) if existing else
                await platform.door.start_run(request_text, channel=channel,
                                              actor_external_id=actor_external_id, source_ref=source_ref))
        if idempotency_key:
            await repo.dedupe_webhook(c, source, idempotency_key, view.run_id)

    fs = platform.registry.get("freshservice")
    async with advisory_lock(platform.db, f"{source}-ticket:{view.run_id}") as c:
        row = await (await c.execute(
            "select ref from door_messages where run_id = %s and action_id = '' and channel = 'freshservice'",
            (view.run_id,))).fetchone()
        if row:
            return VoiceRequestResult(run=view, ticket=VoiceTicket.model_validate(row["ref"]))
        # Commit before POST: an uncertain outcome is durable and cannot trigger a duplicate ticket.
        await repo.upsert_door_message(c, view.run_id, "freshservice", {"status": "attempted", "mode": fs.mode})

    try:
        direct = False
        try:
            placed = await fs.place_access_request(actor["email"], request_text)
        except FreshserviceHTTPError as e:
            if e.status != 403 or fs.mode != "LIVE":
                raise
            direct = True
            placed = await fs.create_incident_ticket(
                email=actor["email"], subject=f"[ContextRail {ticket_tag or source}] Request {view.run_id}",
                description=request_text)
        ticket_id = fs_id(placed.data["id"])
        try:
            seen = await fs.get_ticket(ticket_id)
            if direct:
                description = str(seen.data.get("description_text") or seen.data.get("description") or "")
                workspace_id = getattr(getattr(fs, "live", None), "workspace_id", None)
                verified = (seen.mode == placed.mode and seen.data.get("id") == ticket_id and
                            (workspace_id is None or seen.data.get("workspace_id") == workspace_id) and
                            seen.data.get("subject") == f"[ContextRail {ticket_tag or source}] Request {view.run_id}" and
                            request_text in description)
            else:
                items = await fs.get_requested_items(ticket_id)
                verified = (seen.mode == placed.mode and items.mode == placed.mode and
                            seen.data.get("id") == ticket_id and any(
                                item.get("custom_fields", {}).get(ACCESS_REQUEST_TEXT_FIELD) == request_text
                                for item in items.data))
        except ConnectorError:
            verified = False
        ticket = VoiceTicket(status="verified" if verified else "unverified", ticket_id=ticket_id,
                             mode=placed.mode)
    except UnknownOutcome:
        ticket = VoiceTicket(status="unknown", mode=fs.mode)
    except (ConnectorError, KeyError, TypeError, ValueError):
        ticket = VoiceTicket(status="blocked", mode=fs.mode)

    async with platform.db.transaction() as c:
        await repo.upsert_door_message(c, view.run_id, "freshservice", ticket.model_dump(exclude_none=True))
        if ticket.status == "verified":
            for action in await repo.list_actions(c, view.run_id):
                if action["state"] == "awaiting":
                    await repo.enqueue_job(c, "approval.dispatch",
                                           {"run_id": str(view.run_id), "action_id": action["id"]},
                                           dedupe_key=f"approval.dispatch:ticket:{view.run_id}:{action['id']}")
    if ticket.status == "verified" and ticket.mode == "LIVE" and ticket.ticket_id is not None:
        async with platform.db.connection() as c:
            run = await repo.get_run(c, view.run_id)
        if run and run.get("intent") == "onboarding":
            try:
                tasks = await fs.ensure_onboarding_tasks(ticket.ticket_id)
                task_ref = {"status": "verified", "task_ids": [fs_id(task["id"]) for task in tasks],
                            "mode": "LIVE"}
            except (ConnectorError, KeyError, TypeError, ValueError):
                task_ref = {"status": "blocked", "mode": "LIVE"}
            async with platform.db.transaction() as c:
                await repo.upsert_door_message(c, view.run_id, "freshservice", task_ref,
                                               action_id="onboarding-tasks")
            article_id = get_settings().fs_onboarding_sop_article_id
            if article_id:
                marker = f"cr-onboarding-sop-{view.run_id.hex}"
                try:
                    article = await fs.get_solution_article(article_id)
                    if article.mode != "LIVE" or fs_id(article.data["id"]) != article_id:
                        raise ConnectorError("Freshservice onboarding SOP could not be verified")
                    subject = escape(view.subject or "unresolved worker")
                    title = escape(str(article.data.get("title") or "Contractor onboarding SOP"))
                    domain = get_settings().fs_domain
                    link = f"https://{domain}/a/solutions/articles/{article_id}"
                    rows = "".join(
                        f"<li>{escape(row.label)}: {escape(row.state)} ({row.connector_mode})</li>"
                        for row in view.rows
                    )
                    body = (f"<p>ContextRail onboarding context for {subject}. "
                            f"Run {escape(str(view.run_id))}.</p>"
                            f"<p>Procedure: <a href=\"{escape(link, quote=True)}\">{title}</a> "
                            f"(Freshservice article #{article_id}, draft).</p>"
                            f"<p>Recorded actions and holds:</p><ul>{rows}</ul>"
                            "<p>Confirm HRIS, signed SOW, equipment, guest scope, and access readback "
                            "before closing this ticket. FIXTURE connector results are demo evidence only.</p>")
                    note = await fs.add_private_note(ticket.ticket_id, body, marker)
                    status = "verified" if note.mode == "LIVE" and note.confirmed else "unverified"
                    ref = {"status": status, "article_id": article_id, "note_id": note.note_id,
                           "mode": note.mode}
                except (ConnectorError, KeyError, TypeError, ValueError):
                    ref = {"status": "blocked", "article_id": article_id, "mode": "LIVE"}
                async with platform.db.transaction() as c:
                    await repo.upsert_door_message(c, view.run_id, "freshservice", ref,
                                                   action_id="onboarding-sop")
    return VoiceRequestResult(run=view, ticket=ticket)

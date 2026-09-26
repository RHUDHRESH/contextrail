"""Worker bridge for approval jobs emitted by the rail and every decision door.

Each delivery function owns its own read-before-write idempotency. A retry can therefore
re-run this bridge after a partial delivery without sending a duplicate card or note.
"""

from __future__ import annotations

from contextrail.connectors.ses import SesConnector
from contextrail.jobs import PermanentJobError, handler
from contextrail.logs import get_logger
from contextrail.surfaces.decision_link import LinkSigner, WeakSecret
from contextrail.surfaces.email import EmailDoorContext, handle_approval_dispatch_email
from contextrail.surfaces.freshservice import handle_fs_approval_mirror, handle_fs_approval_request
from contextrail.surfaces.slack_app import handle_approval_dispatch, handle_door_update

log = get_logger("contextrail.jobs.approval")


@handler("approval.dispatch")
async def approval_dispatch(platform, payload: dict) -> None:
    """Ask in Freshservice when ticket-backed, in Slack when available, and by email when preferred."""
    fs = await handle_fs_approval_request(payload, platform)
    slack = getattr(platform, "slack", None)
    slack_result = await handle_approval_dispatch(payload, slack) if slack is not None else None

    email_result = None
    try:
        signer = LinkSigner(platform.settings.decision_link_secret)
    except WeakSecret:
        signer = None
    if signer is not None:
        ctx = EmailDoorContext(door=platform.door, ses=SesConnector(platform.settings), signer=signer,
                               public_url=platform.settings.public_url)
        email_result = await handle_approval_dispatch_email(payload, ctx)

    delivered = (fs["status"] in {"requested", "exists"}
                 or (slack_result and slack_result.get("status") in {"delivered", "already_delivered"})
                 or (email_result and email_result.outcome in {"sent", "replayed"}))
    if not delivered:
        raise PermanentJobError("no approval could be delivered through Freshservice, Slack, or email")
    log.info("approval_dispatched", run_id=payload.get("run_id"), action_id=payload.get("action_id"),
             freshservice=fs["status"], slack=slack_result and slack_result.get("status"),
             email=email_result and email_result.outcome)


@handler("fs.approval.mirror")
async def approval_mirror(platform, payload: dict) -> None:
    """Mirror a recorded cross-door decision as a read-back-verified private ticket note."""
    result = await handle_fs_approval_mirror(payload, platform)
    log.info("approval_mirror_processed", run_id=payload.get("run_id"), action_id=payload.get("action_id"),
             status=result["status"])


@handler("door.update")
async def door_update(platform, payload: dict) -> None:
    """Refresh cards after a decision; email links read the current state on their confirmation page."""
    slack = getattr(platform, "slack", None)
    if slack is not None:
        result = await handle_door_update(payload, slack)
        log.info("door_card_updated", run_id=payload.get("run_id"), action_id=payload.get("action_id"),
                 slack=result.get("status"))

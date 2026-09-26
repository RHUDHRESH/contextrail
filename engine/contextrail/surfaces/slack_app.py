"""The Slack door (CLAUDE.md §13.1, checklist section J).

A thin translator between Slack and the door contract: Slack payloads become `Door` calls, and `RunView`s become
Block Kit. Nothing here decides a verdict, an approval or an identity (D-005); `Door` does.

The door is LIVE only when SLACK_BOT_TOKEN and SLACK_SIGNING_SECRET are set (`settings.slack_configured`, D-004).
Production runs in HTTP mode: `main.py` includes `router` (POST /slack/events, the URL in slack/manifest.yaml)
only when configured, and `attach(app, door)` binds the Bolt app once a rail exists. Development can use Socket
Mode instead (`contextrail.surfaces.slack_socket`). Every request is signature-checked by Bolt before a handler runs.
"""

from __future__ import annotations

import re
from uuid import UUID

from fastapi import APIRouter, FastAPI, HTTPException, Request
from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler
from slack_bolt.async_app import AsyncApp
from slack_bolt.authorization import AuthorizeResult
from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient

from contextrail import repo
from contextrail.logs import get_logger
from contextrail.models import RunStatus, StageEvent
from contextrail.surfaces import slack_blocks as blocks
from contextrail.surfaces.door import DecisionResult, Door
from contextrail.surfaces.presenter import RunView

EVENTS_PATH = "/slack/events"
COMMAND = "/contextrail"
log = get_logger("contextrail.slack")


class SlackDoor:
    """The Bolt app plus the Web API client, bound to one Door."""

    def __init__(self, door: Door, *, client: AsyncWebClient, signing_secret: str,
                 process_before_response: bool = False) -> None:
        self.door, self.client = door, client
        auth: list[AuthorizeResult] = []

        async def authorize() -> AuthorizeResult:
            # Bolt builds a fresh AsyncWebClient for every request (slack_bolt >= 1.15). Authorizing here keeps
            # auth.test on the door's own client, once per process, like single-workspace authorization would.
            if not auth:
                auth.append(AuthorizeResult.from_auth_test_response(bot_token=client.token,
                                                                    auth_test_response=await client.auth_test()))
            return auth[0]

        # process_before_response=False (default): Bolt returns the ack to Slack at once, within its 3 s deadline,
        # and the handler carries on. Tests set it True so a signed request finishes its work before the response.
        self.app = AsyncApp(name="contextrail", client=client, authorize=authorize, signing_secret=signing_secret,
                            process_before_response=process_before_response)
        self.http = AsyncSlackRequestHandler(self.app)
        self.app.command(COMMAND)(self.on_command)
        self.app.action("approve")(self.on_decision)
        self.app.action("refuse")(self.on_decision)
        self.app.action(re.compile(r"^pick_candidate:\d+$"))(self.on_pick)
        self._status: dict[UUID, dict | None] = {}  # run id -> its status message {channel, ts, request_text}
        self._askers: dict[tuple[str, str], str] = {}  # (channel, ts) of a status message -> who typed the command
        door.runner.d.events.on_every_run(self.on_stage_event)

    # --- /contextrail <request> ---------------------------------------------------------------------------------

    async def on_command(self, ack, command: dict) -> None:
        """Acknowledge at once (Slack's 3 s deadline; ephemeral, so only the requester sees it), post the one
        status message this run will edit, then hand the request to the Door. Who asked is the Slack user id; the
        Door maps it through identity_map. The run's source_ref is that message ("<channel>:<ts>", CLAUDE.md §6)."""
        text = (command.get("text") or "").strip()
        if not text:
            await ack(text=blocks.USAGE, response_type="ephemeral")
            return
        await ack(text=blocks.ack_text(text), response_type="ephemeral")
        channel, ts = await self._post_status(command["channel_id"], command["user_id"], text)
        self._askers[(channel, ts)] = command["user_id"]
        await self.door.start_run(text, channel="slack", actor_external_id=command["user_id"],
                                  source_ref=f"{channel}:{ts}")

    # --- "which Rahul?" -> Door.pick_candidate ----------------------------------------------------------------

    async def on_pick(self, ack, body: dict, action: dict) -> RunView | None:
        """A candidate button on the status message. The question was asked to the Slack user who typed the
        command, so only they answer it; the rail looks the chosen ID up exactly, like any other mention."""
        await ack()
        parsed = blocks.parse_pick_value(action.get("value"))
        if parsed is None:
            await self._tell(body, blocks.rejected_text("this button is damaged"))
            return None
        run_id, role, source_id = parsed
        asker = await self._asker(run_id)
        if asker and body["user"]["id"] != asker:
            await self._tell(body, blocks.not_yours_text(asker))
            return None
        try:
            return await self.door.pick_candidate(run_id, role, source_id)
        except ValueError:  # the rail refuses to re-run a run that is no longer waiting for this answer
            await self._tell(body, blocks.ANSWERED_TEXT)
            return None

    async def _asker(self, run_id: UUID) -> str | None:
        async with self.door.db.connection() as c:
            refs = [m["ref"] for m in await repo.list_door_messages(c, run_id) if m["channel"] == "slack"]
        return refs[0].get("user") if refs else None

    async def _post_status(self, channel: str, user: str, text: str) -> tuple[str, str]:
        """In the channel the command came from; in the requester's DM if the bot is not a member there."""
        try:
            resp = await self.client.chat_postMessage(channel=channel, **blocks.starting_message(text))
        except SlackApiError as e:
            if e.response.get("error") not in ("not_in_channel", "channel_not_found"):
                raise
            dm = (await self.client.conversations_open(users=user))["channel"]["id"]
            resp = await self.client.chat_postMessage(channel=dm, **blocks.starting_message(text))
        return resp["channel"], resp["ts"]

    # --- approval cards ----------------------------------------------------------------------------------------

    async def deliver_approval_card(self, run_id: UUID, action_id: str) -> dict:
        """Post the approval card to the named approver's DM, once. The card is rendered from the current RunView,
        so it binds the parameters the action has now; door_messages records where it lives (and is the
        idempotency record: a retried job finds it and sends nothing)."""
        async with self.door.db.connection() as c:
            sent = [m for m in await repo.list_door_messages(c, run_id, action_id) if m["channel"] == "slack"]
        if sent:
            return {"status": "already_delivered", "ref": sent[0]["ref"]}
        view = await self.door.get_status(run_id)
        row = next((r for r in view.rows if r.action_id == action_id), None)
        if row is None or row.state != "awaiting":
            return {"status": "not_awaiting"}
        user = await self.slack_user_for(row.approver_id)
        if user is None:
            return {"status": "no_slack_user"}
        dm = (await self.client.conversations_open(users=user))["channel"]["id"]
        resp = await self.client.chat_postMessage(channel=dm, **blocks.approval_card(view, row))
        ref = {"channel": resp["channel"], "ts": resp["ts"], "user": user}
        async with self.door.db.transaction() as c:
            await repo.upsert_door_message(c, run_id, "slack", ref, action_id=action_id)
        return {"status": "delivered", "ref": ref}

    async def on_decision(self, ack, body: dict, action: dict) -> DecisionResult | None:
        """Approve / Refuse on a card. The button says which action and which parameters; the clicker is whoever
        Slack says clicked. Door.decide checks everything else (identity, named approver, state, params_hash,
        separation of duties, first decision wins)."""
        await ack()
        parsed = blocks.parse_decision_value(action.get("value"))
        if parsed is None:
            log.warning("slack_decision_value_invalid", action_id=action.get("action_id"))
            await self._tell(body, blocks.rejected_text("this button is damaged"))
            return None
        run_id, action_id, params_hash = parsed
        result = await self.door.decide(run_id, action_id, params_hash, channel="slack",
                                        actor_external_id=body["user"]["id"],
                                        decision="approved" if action["action_id"] == "approve" else "refused")
        if result.outcome == "rejected":  # the card stays as it is, for the person who can decide it
            await self._tell(body, blocks.rejected_text(result.reason))
        else:  # recorded here, or already decided in some door: the card shows who, where and when, at once
            await self.refresh_card(run_id, action_id)
        return result

    async def refresh_card(self, run_id: UUID, action_id: str) -> dict:
        """Re-render this action's Slack card from the stored decision and the current RunView. Idempotent: the
        door.update job and the click handler may both call it."""
        async with self.door.db.connection() as c:
            cards = [m["ref"] for m in await repo.list_door_messages(c, run_id, action_id) if m["channel"] == "slack"]
            decision = await repo.get_approval(c, run_id, action_id)
        if not cards:
            return {"status": "no_card"}
        if decision is None:
            return {"status": "undecided"}
        view = await self.door.get_status(run_id)
        row = next(r for r in view.rows if r.action_id == action_id)
        content = blocks.decided_card(view, row, decision)
        for ref in cards:
            await self.client.chat_update(channel=ref["channel"], ts=ref["ts"], **content)
        return {"status": "updated"}

    async def _tell(self, body: dict, text: str) -> None:
        """An ephemeral note to whoever clicked, where they clicked; nobody else sees it."""
        channel = (body.get("channel") or {}).get("id") or (body.get("container") or {}).get("channel_id")
        await self.client.chat_postEphemeral(channel=channel, user=body["user"]["id"], text=text)

    # --- identity: person -> Slack user, for delivering cards ---------------------------------------------------

    async def slack_user_for(self, person_id: str) -> str | None:
        """The Slack user to DM for a person: identity_map.slack_user_id, else Slack's users.lookupByEmail on the
        mapped email. An email match is written back (only where empty) so the Door can map that person's clicks
        back to them. A Slack account already mapped to someone else is never linked, and never messaged."""
        async with self.door.db.connection() as c:
            row = await (await c.execute("select slack_user_id, email from identity_map where person_id = %s",
                                         (person_id,))).fetchone()
        if row is None or row["slack_user_id"] or not row["email"]:
            return row["slack_user_id"] if row else None
        try:
            uid = (await self.client.users_lookupByEmail(email=row["email"]))["user"]["id"]
        except SlackApiError as e:
            if e.response.get("error") == "users_not_found":
                return None
            raise
        async with self.door.db.transaction() as c:
            owner = await (await c.execute("select person_id from identity_map where slack_user_id = %s",
                                           (uid,))).fetchone()
            if owner is None:
                await c.execute("update identity_map set slack_user_id = %s where person_id = %s "
                                "and slack_user_id is null", (uid, person_id))
        if owner is not None and owner["person_id"] != person_id:
            log.warning("slack_identity_conflict", person_id=person_id, owner=owner["person_id"])
            return None
        return uid

    # --- stage events -> the status message, edited in place ---------------------------------------------------

    async def on_stage_event(self, event: StageEvent) -> None:
        """EventBus callback for every run. Runs that did not start in Slack are ignored. While the rail runs the
        message shows the step; when it pauses or ends it shows the whole RunView."""
        msg = await self._status_message(event.run_id)
        if event.status in _SETTLED:
            self._status.pop(event.run_id, None)
        if msg is None:
            return
        content = (blocks.stage_message(msg["request_text"], event) if event.status == RunStatus.RUNNING
                   else blocks.run_summary(await self.door.get_status(event.run_id)))
        await self.client.chat_update(channel=msg["channel"], ts=msg["ts"], **content)

    async def _status_message(self, run_id: UUID) -> dict | None:
        if run_id in self._status:
            return self._status[run_id]
        async with self.door.db.connection() as c:
            run = await repo.get_run(c, run_id)
        msg = _status_ref(run) if run else None
        if msg is not None:
            ref = {"channel": msg["channel"], "ts": msg["ts"]}
            if asker := self._askers.pop((msg["channel"], msg["ts"]), None):
                ref["user"] = asker
            async with self.door.db.transaction() as c:  # where the message lives, so later updates can find it
                await repo.upsert_door_message(c, run_id, "slack", ref)
            msg["request_text"] = run["request_text"]
        self._status[run_id] = msg
        return msg


# --- job handlers (the worker passes the SlackDoor as ctx) ------------------------------------------------------

async def handle_approval_dispatch(payload: dict, ctx: SlackDoor) -> dict:
    """Job kind 'approval.dispatch' (enqueued per held action by rail/approve.dispatch_holds)."""
    return await ctx.deliver_approval_card(UUID(str(payload["run_id"])), payload["action_id"])


async def handle_door_update(payload: dict, ctx: SlackDoor) -> dict:
    """Job kind 'door.update' (enqueued by Door.decide after a decision in any door): refresh the Slack card."""
    return await ctx.refresh_card(UUID(str(payload["run_id"])), payload["action_id"])


_SETTLED = {RunStatus.DONE, RunStatus.PARTIAL, RunStatus.FAILED}
_STATUS_REF = re.compile(r"^(?P<channel>[A-Z0-9]+):(?P<ts>\d+\.\d+)$")


def _status_ref(run: dict) -> dict | None:
    """A Slack-started run's source_ref names its status message."""
    m = _STATUS_REF.match(run.get("source_ref") or "") if run.get("source") == "slack" else None
    return {"channel": m["channel"], "ts": m["ts"]} if m else None


router = APIRouter()


@router.post(EVENTS_PATH, include_in_schema=False)
async def slack_events(request: Request):
    """Slash commands, button clicks and events, all signed by Slack; Bolt verifies before any handler runs."""
    slack: SlackDoor | None = getattr(request.app.state, "slack", None)
    if slack is None:
        raise HTTPException(503, "The Slack door is configured but not attached to a rail yet.")
    return await slack.http.handle(request)


def attach(app: FastAPI, door: Door, *, client: AsyncWebClient | None = None) -> SlackDoor:
    """Bind the Slack door to the app's rail. Called where the app builds its Door."""
    settings = app.state.settings
    if not settings.slack_configured:
        raise RuntimeError("Slack is not configured: set SLACK_BOT_TOKEN and SLACK_SIGNING_SECRET")
    slack = SlackDoor(door, client=client or AsyncWebClient(token=settings.slack_bot_token.get_secret_value()),
                      signing_secret=settings.slack_signing_secret.get_secret_value())
    app.state.slack = slack
    return slack

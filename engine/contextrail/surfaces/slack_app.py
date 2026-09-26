"""The Slack door (CLAUDE.md §13.1, checklist section J).

A thin translator between Slack and the door contract: Slack payloads become `Door` calls, and `RunView`s become
Block Kit. Nothing here decides a verdict, an approval or an identity (D-005); `Door` does.

The door is LIVE only when SLACK_BOT_TOKEN and SLACK_SIGNING_SECRET are set (`settings.slack_configured`, D-004).
Production runs in HTTP mode: `main.py` includes `router` (POST /slack/events, the URL in slack/manifest.yaml)
only when configured, and `attach(app, door)` binds the Bolt app once a rail exists. Development can use Socket
Mode instead (`contextrail.surfaces.slack_socket`). Every request is signature-checked by Bolt before a handler runs.
"""

from __future__ import annotations

from fastapi import APIRouter, FastAPI, HTTPException, Request
from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler
from slack_bolt.async_app import AsyncApp
from slack_sdk.web.async_client import AsyncWebClient

from contextrail.surfaces.door import Door

EVENTS_PATH = "/slack/events"


class SlackDoor:
    """The Bolt app plus the Web API client, bound to one Door."""

    def __init__(self, door: Door, *, client: AsyncWebClient, signing_secret: str,
                 process_before_response: bool = False) -> None:
        self.door, self.client = door, client
        # process_before_response=False (default): Bolt returns the ack to Slack at once, within its 3 s deadline,
        # and the handler carries on. Tests set it True so a signed request finishes its work before the response.
        self.app = AsyncApp(name="contextrail", client=client, signing_secret=signing_secret,
                            process_before_response=process_before_response)
        self.http = AsyncSlackRequestHandler(self.app)


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

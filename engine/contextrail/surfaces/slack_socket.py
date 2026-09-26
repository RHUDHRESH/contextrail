"""Slack door over Socket Mode, for development (CLAUDE.md §13.1): `python -m contextrail.surfaces.slack_socket`.

Slack delivers slash commands and button clicks over a websocket, so a laptop with no public URL can run the door.
It needs SLACK_BOT_TOKEN and SLACK_APP_TOKEN (an app-level token with connections:write), and
refuses to start without them rather than pretend. HTTP mode also needs SLACK_SIGNING_SECRET.
Production uses HTTP mode (POST /slack/events) instead.

The rail is built from the same Settings and Platform as the HTTP app, including connector modes and the approval
worker. It talks to DATABASE_URL, so run `python -m contextrail.seed` first.
"""

from __future__ import annotations

import asyncio
import secrets
import sys

from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_sdk.web.async_client import AsyncWebClient

from contextrail.settings import Settings, get_settings
from contextrail.surfaces.slack_app import SlackDoor


def build_handler(slack: SlackDoor, *, app_token: str) -> AsyncSocketModeHandler:
    """The Socket Mode handler for this door's Bolt app. Constructing it does not connect."""
    return AsyncSocketModeHandler(slack.app, app_token=app_token)


async def _serve(settings: Settings) -> None:
    from contextrail.app_state import build_platform

    platform = build_platform(settings)
    # Socket Mode receives callbacks over a websocket; this signing secret is never used to admit HTTP traffic.
    signing_secret = settings.slack_signing_secret.get_secret_value() or secrets.token_urlsafe(32)
    slack = SlackDoor(platform.door, client=AsyncWebClient(token=settings.slack_bot_token.get_secret_value()),
                      signing_secret=signing_secret)
    slack.platform = platform
    platform.slack = slack
    handler = build_handler(slack, app_token=settings.slack_app_token.get_secret_value())
    async with platform.serving(worker=True):
        try:
            await handler.start_async()
        finally:
            await handler.close_async()


def main(settings: Settings | None = None) -> int:
    settings = settings or get_settings()
    missing = [name for name, secret in (("SLACK_BOT_TOKEN", settings.slack_bot_token),
                                         ("SLACK_APP_TOKEN", settings.slack_app_token))
               if not secret.get_secret_value()]
    if missing:
        print(f"slack_socket: not starting, set {', '.join(missing)}", file=sys.stderr)
        return 2
    # psycopg's async mode cannot run on Windows' default Proactor loop (see db.py).
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    asyncio.run(_serve(settings), loop_factory=loop_factory)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

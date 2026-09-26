"""Slack door over Socket Mode, for development (CLAUDE.md §13.1): `python -m contextrail.surfaces.slack_socket`.

Slack delivers slash commands and button clicks over a websocket, so a laptop with no public URL can run the door.
It needs SLACK_BOT_TOKEN, SLACK_SIGNING_SECRET and SLACK_APP_TOKEN (an app-level token with connections:write), and
refuses to start without them rather than pretend. Production uses HTTP mode (POST /slack/events) instead.

The rail wired here is the fixture-backed one the tests use (heuristic intent reader, template explanations); it
talks to DATABASE_URL, so run `python -m contextrail.seed` first.
"""

from __future__ import annotations

import asyncio
import sys

from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_sdk.web.async_client import AsyncWebClient

from contextrail.settings import Settings, get_settings
from contextrail.surfaces.slack_app import SlackDoor


def build_handler(slack: SlackDoor, *, app_token: str) -> AsyncSocketModeHandler:
    """The Socket Mode handler for this door's Bolt app. Constructing it does not connect."""
    return AsyncSocketModeHandler(slack.app, app_token=app_token)


async def _serve(settings: Settings) -> None:
    from contextrail.connectors.registry import build_registry
    from contextrail.db import Database
    from contextrail.fixtures import load
    from contextrail.policy.engine import PolicyEngine
    from contextrail.policy.loader import load_rules
    from contextrail.rail.discover import HeuristicExtractor
    from contextrail.rail.plan import TemplateExplainer
    from contextrail.rail.runner import RailDeps, Runner
    from contextrail.seed import approver_directory
    from contextrail.surfaces.door import Door

    people = {p["person_id"]: p["display_name"] for p in load("identity")["people"]}
    rules, registry = load_rules(), build_registry()
    db = Database(settings.database_url)
    await db.open()
    try:
        runner = Runner(RailDeps(db=db, registry=registry, engine=PolicyEngine(rules, approver_directory()),
                                 rules=rules, extractor=HeuristicExtractor(), explainer=TemplateExplainer(people)))
        modes = {name: c.mode for name, c in registry.connectors.items()}
        slack = SlackDoor(Door(runner, people=people, modes=modes),
                          client=AsyncWebClient(token=settings.slack_bot_token.get_secret_value()),
                          signing_secret=settings.slack_signing_secret.get_secret_value())
        handler = build_handler(slack, app_token=settings.slack_app_token.get_secret_value())
        try:
            await handler.start_async()
        finally:
            await handler.close_async()
    finally:
        await db.close()


def main(settings: Settings | None = None) -> int:
    settings = settings or get_settings()
    missing = [name for name, secret in (("SLACK_BOT_TOKEN", settings.slack_bot_token),
                                         ("SLACK_SIGNING_SECRET", settings.slack_signing_secret),
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

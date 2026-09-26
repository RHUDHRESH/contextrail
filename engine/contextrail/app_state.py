"""The composition root: the one place the engine's object graph is built from Settings.

`main.create_app()` and the job worker (`python -m contextrail.worker`) both build a Platform here, so the HTTP
API, the job handlers and every door share one Database pool, one policy engine, one EventBus, one Runner and one
Door (D-005: doors call only door.py). The lifespan opens the pool on startup and closes it on shutdown.

Tests inject a Runner built over their own database and FIXTURE state (conftest `rail`). The Platform then does not
own the pool: whoever opened it closes it.

The extractor and explainer are the offline ones (heuristic intent, template explanations), labelled as such
wherever they show. The LLM router (section H) replaces them here, and nowhere else.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from contextrail.connectors.registry import Registry, build_registry
from contextrail.db import Database
from contextrail.fixtures import load
from contextrail.policy.engine import PolicyEngine
from contextrail.policy.loader import load_rules
from contextrail.policy.schema import Rule
from contextrail.rail.discover import HeuristicExtractor
from contextrail.rail.events import EventBus
from contextrail.rail.plan import TemplateExplainer
from contextrail.rail.runner import RailDeps, Runner
from contextrail.seed import approver_directory
from contextrail.settings import Settings
from contextrail.surfaces.door import Door


def people_names() -> dict[str, str]:
    """person_id -> display name, from the same identity file the seed loads into identity_map (FIXTURE)."""
    return {p["person_id"]: p["display_name"] for p in load("identity")["people"]}


@dataclass
class Platform:
    settings: Settings
    runner: Runner
    door: Door
    owns_db: bool = True
    sse_heartbeat_s: float = 15.0

    @property
    def db(self) -> Database:
        return self.runner.d.db

    @property
    def events(self) -> EventBus:
        return self.runner.d.events

    @property
    def registry(self) -> Registry:
        return self.runner.d.registry

    @property
    def rules(self) -> list[Rule]:
        return self.runner.d.rules

    @property
    def modes(self) -> dict[str, str]:
        return self.door.modes

    @asynccontextmanager
    async def lifespan(self, _app) -> AsyncIterator[None]:
        if self.owns_db:
            await self.db.open()
        try:
            yield
        finally:
            if self.owns_db:
                await self.db.close()


def build_platform(settings: Settings, *, rules: list[Rule] | None = None, runner: Runner | None = None,
                   sse_heartbeat_s: float = 15.0) -> Platform:
    """Build the object graph. Pass `runner` to reuse an existing rail (and its already-open pool)."""
    owns_db = runner is None
    if runner is None:
        rules = load_rules() if rules is None else rules
        registry = build_registry(Path(settings.state_dir) if settings.state_dir else None)
        runner = Runner(RailDeps(
            db=Database(settings.database_url), registry=registry,
            engine=PolicyEngine(rules, approver_directory()), rules=rules,
            extractor=HeuristicExtractor(), explainer=TemplateExplainer(people_names())))
    modes = {name: c.mode for name, c in runner.d.registry.connectors.items()}
    door = Door(runner, people=people_names(), modes=modes)
    return Platform(settings=settings, runner=runner, door=door, owns_db=owns_db, sse_heartbeat_s=sse_heartbeat_s)

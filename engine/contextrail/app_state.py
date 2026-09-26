"""The composition root: the one place the engine's object graph is built from Settings.

`main.create_app()` and the job worker (`python -m contextrail.worker`) both build a Platform here, so the HTTP
API, the job handlers and every door share one Database pool, one policy engine, one EventBus, one Runner and one
Door (D-005: doors call only door.py). The lifespan opens the pool on startup and closes it on shutdown, and runs
the job worker in the API process unless WORKER_IN_PROCESS=false, so runs started by webhook jobs stream their
StageEvents to the same EventBus that SSE reads.

Tests inject a Runner built over their own database and FIXTURE state (conftest `rail`). The Platform then does not
own the pool: whoever opened it closes it.

The extractor and explainer are the offline ones (heuristic intent, template explanations), labelled as such
wherever they show. The LLM router (section H) replaces them here, and nowhere else.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from contextrail.connectors.registry import Registry, build_registry
from contextrail.db import Database
from contextrail.fixtures import load
from contextrail.intake import TicketReader
from contextrail.jobs import Worker, load_handlers
from contextrail.logs import get_logger
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

log = get_logger("contextrail.app")


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
    tickets: TicketReader | None = None      # Freshservice ticket reads for 'rail.run' {ticket_id} (section I)
    shutdown_grace_s: float = 8.0            # under Docker's 10 s stop timeout
    worker: Worker | None = field(default=None, init=False)

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

    def lifespan(self, _app):
        """FastAPI lifespan: the pool, plus the in-process job worker unless WORKER_IN_PROCESS=false."""
        return self.serving(worker=self.settings.worker_in_process)

    @asynccontextmanager
    async def serving(self, *, worker: bool) -> AsyncIterator[None]:
        """Open the pool (if owned) and optionally run a job worker in this process, whose StageEvents then reach
        this process's EventBus (SSE, door callbacks). On exit the worker finishes its current job first (bounded by
        `shutdown_grace_s`; a job cut off there is retried once its lease expires)."""
        if self.owns_db:
            await self.db.open()
        task = None
        if worker:
            load_handlers()
            self.worker = Worker(self.db, self)
            task = asyncio.create_task(self.worker.run(), name="contextrail-worker")
        try:
            yield
        finally:
            if task is not None:
                self.worker.stop()
                try:
                    await asyncio.wait_for(task, timeout=self.shutdown_grace_s)
                except TimeoutError:
                    log.warning("worker_cut_off_at_shutdown", grace_s=self.shutdown_grace_s)
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

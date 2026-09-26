"""The composition root: one object graph per process, built from Settings, with the pool owned by the lifespan."""

import asyncio

import psycopg_pool
import pytest

from contextrail import repo
from contextrail.app_state import Platform, build_platform
from contextrail.jobs import load_handlers
from contextrail.main import create_app
from contextrail.rail.discover import HeuristicExtractor
from contextrail.rail.plan import TemplateExplainer
from contextrail.settings import Settings


def test_create_app_builds_one_platform_every_part_shares(tmp_path):
    app = create_app(Settings(_env_file=None, state_dir=str(tmp_path)))
    p: Platform = app.state.platform
    assert p.door.runner is p.runner and p.door.db is p.db and p.events is p.runner.d.events
    assert app.state.door is p.door  # email decision links use the same Door as every other surface
    assert app.state.registry is p.registry and app.state.rules is p.rules
    assert isinstance(p.runner.d.extractor, HeuristicExtractor) and isinstance(p.runner.d.explainer, TemplateExplainer)
    assert {r.id for r in p.rules} >= {"POL-CTR-001", "POL-SOD-001"}
    assert p.modes == {"entitlements": "FIXTURE", "freshservice": "FIXTURE", "github": "FIXTURE", "hris": "FIXTURE",
                       "slack_corpus": "FIXTURE"}  # freshservice: FIXTURE until FS_DOMAIN + FS_API_KEY exist
    assert p.door.people["p-dana"] == "Dana Osei"
    assert p.owns_db


async def test_lifespan_opens_the_pool_and_closes_it(migrated_db, tmp_path):
    app = create_app(Settings(_env_file=None, database_url=migrated_db, state_dir=str(tmp_path)))
    db = app.state.platform.db
    async with app.router.lifespan_context(app), db.connection() as c:
        assert (await (await c.execute("select 1 as one")).fetchone())["one"] == 1
    with pytest.raises(psycopg_pool.PoolClosed):
        async with db.connection():
            pass


async def test_the_api_process_runs_a_worker_whose_stage_events_reach_the_api(migrated_db, tmp_path):
    app = create_app(Settings(_env_file=None, database_url=migrated_db, state_dir=str(tmp_path),
                              worker_in_process=True))
    p: Platform = app.state.platform
    async with app.router.lifespan_context(app):
        assert "rail.run" in p.worker.registry.kinds()
        rid = await p.runner.start(source="freshservice", request_text="Give Anil the same access as Rahul Mehta",
                                   source_ref="9")
        async with p.db.transaction() as c:
            await repo.enqueue_job(c, "rail.run", {"run_id": str(rid)})
        for _ in range(300):  # the worker polls every second
            if [e for e in p.events.history(rid) if e.stage == "finalize"]:
                break
            await asyncio.sleep(0.1)
    assert p.events.history(rid)[-1].status == "awaiting_approval"   # SSE in this process sees worker runs


async def test_the_worker_can_run_in_its_own_process_instead(migrated_db, tmp_path):
    app = create_app(Settings(_env_file=None, database_url=migrated_db, state_dir=str(tmp_path),
                              worker_in_process=False))
    async with app.router.lifespan_context(app):
        assert app.state.platform.worker is None


def test_handler_modules_register_the_built_in_kinds():
    assert {"rail.run"} <= set(load_handlers())


async def test_an_injected_platform_is_used_and_its_pool_is_left_to_its_owner(rail):
    runner, deps = rail
    settings = Settings(_env_file=None)
    platform = build_platform(settings, runner=runner)
    app = create_app(settings, platform=platform)
    assert app.state.platform is platform and not platform.owns_db and platform.registry is deps.registry
    async with app.router.lifespan_context(app):
        pass
    async with deps.db.connection() as c:  # still open: the rail fixture owns it
        assert (await (await c.execute("select 1 as one")).fetchone())["one"] == 1

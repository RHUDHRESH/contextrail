"""Shared fixtures. Database tests run against a real PostgreSQL 16 (embedded via pgserver, see DECISIONS D-009).

Set CONTEXTRAIL_TEST_DATABASE_URL to use an existing server instead (e.g. the compose postgres in CI).
Each test gets its own freshly created database, so tests never see each other's rows.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
import uuid
from collections.abc import Iterator

import psycopg
import pytest


def pytest_asyncio_loop_factories(config, item):
    # psycopg async cannot run on Windows' default Proactor loop (see contextrail/db.py).
    if sys.platform == "win32":
        return {"selector": asyncio.SelectorEventLoop}
    return {"default": asyncio.new_event_loop}


@pytest.fixture(scope="session")
def pg_server_uri() -> Iterator[str]:
    external = os.environ.get("CONTEXTRAIL_TEST_DATABASE_URL")
    if external:
        yield external
        return
    pgserver = pytest.importorskip("pgserver")
    datadir = tempfile.mkdtemp(prefix="cr-pg-")
    server = pgserver.get_server(datadir, cleanup_mode="stop")
    try:
        yield server.get_uri()
    finally:
        server.cleanup()
        shutil.rmtree(datadir, ignore_errors=True)


def _with_dbname(uri: str, dbname: str) -> str:
    return psycopg.conninfo.make_conninfo(uri, dbname=dbname)


@pytest.fixture
def empty_db(pg_server_uri: str) -> Iterator[str]:
    """A brand-new empty database; dropped after the test."""
    name = f"cr_test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(pg_server_uri, autocommit=True) as c:
        c.execute(f'create database "{name}"')
    try:
        yield _with_dbname(pg_server_uri, name)
    finally:
        with psycopg.connect(pg_server_uri, autocommit=True) as c:
            c.execute(f'drop database if exists "{name}" with (force)')


@pytest.fixture
def migrated_db(empty_db: str) -> str:
    """A new database with every migration applied."""
    from contextrail.migrate import apply_all

    apply_all(empty_db)
    return empty_db


@pytest.fixture
async def rail(migrated_db, tmp_path):
    """A full rail over a fresh migrated database and fresh FIXTURE connector state: (Runner, RailDeps)."""
    from contextrail.connectors.registry import build_registry
    from contextrail.db import Database
    from contextrail.fixtures import load
    from contextrail.policy.engine import PolicyEngine
    from contextrail.policy.loader import load_rules
    from contextrail.rail.discover import HeuristicExtractor
    from contextrail.rail.plan import TemplateExplainer
    from contextrail.rail.runner import RailDeps, Runner
    from contextrail.seed import approver_directory, reset_fixture_state, seed_identity

    reset_fixture_state(tmp_path)
    seed_identity(migrated_db)
    people = {p["person_id"]: p["display_name"] for p in load("identity")["people"]}
    rules = load_rules()

    async def no_sleep(_):
        return None

    db = Database(migrated_db, max_size=4)
    await db.open()
    deps = RailDeps(db=db, registry=build_registry(tmp_path), engine=PolicyEngine(rules, approver_directory()),
                    rules=rules, extractor=HeuristicExtractor(), explainer=TemplateExplainer(people),
                    backoff=lambda n: 0, sleep=no_sleep)
    yield Runner(deps), deps
    await db.close()

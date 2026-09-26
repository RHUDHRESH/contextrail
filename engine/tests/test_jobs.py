"""The job worker: claim with a lease, run the kind's handler, then done / retry with backoff / dead."""

import asyncio

import pytest

from contextrail import repo
from contextrail.db import Database
from contextrail.jobs import HandlerRegistry, PermanentJobError, Worker, retry_delay


@pytest.fixture
async def db(migrated_db):
    async with Database(migrated_db, max_size=4) as d:
        yield d


async def _enqueue(db, kind, payload=None, **kw) -> int:
    async with db.transaction() as c:
        return await repo.enqueue_job(c, kind, payload or {}, **kw)


async def _job(db, job_id) -> dict:
    async with db.connection() as c:
        return await (await c.execute("select * from jobs where id = %s", (job_id,))).fetchone()


def test_a_kind_has_one_handler():
    reg = HandlerRegistry()

    @reg.handler("t.echo")
    async def one(ctx, payload):
        return None

    with pytest.raises(ValueError, match="t.echo"):
        reg.handler("t.echo")(one)
    assert reg.kinds() == ["t.echo"] and reg.get("t.echo") is one and reg.get("nope") is None


def test_default_backoff_doubles_and_is_capped():
    assert [retry_delay(n) for n in (1, 2, 3, 4)] == [5, 10, 20, 40]
    assert retry_delay(30) == 600


def test_the_handler_gets_less_time_than_the_lease():
    with pytest.raises(ValueError, match="lease"):
        Worker(None, None, registry=HandlerRegistry(), lease_s=10, timeout_s=10)


async def test_a_job_runs_once_and_is_done(db):
    reg, seen = HandlerRegistry(), []

    @reg.handler("t.echo")
    async def echo(ctx, payload):
        seen.append((ctx, payload))

    job_id = await _enqueue(db, "t.echo", {"n": 1})
    worker = Worker(db, "ctx", registry=reg)
    out = await worker.run_once()
    assert (out.id, out.kind, out.outcome) == (job_id, "t.echo", "done") and seen == [("ctx", {"n": 1})]
    row = await _job(db, job_id)
    assert row["done"] and row["attempts"] == 1 and row["locked_until"] is None
    assert await worker.run_once() is None


async def test_kinds_without_a_handler_stay_queued_for_a_worker_that_has_one(db):
    reg = HandlerRegistry()

    @reg.handler("t.echo")
    async def echo(ctx, payload):
        return None

    waiting = await _enqueue(db, "approval.dispatch")
    await _enqueue(db, "t.echo")
    worker = Worker(db, None, registry=reg)
    assert (await worker.run_once()).kind == "t.echo"
    assert await worker.run_once() is None
    row = await _job(db, waiting)
    assert not row["done"] and row["attempts"] == 0


async def test_failures_retry_with_backoff_then_the_job_goes_dead(db):
    reg, delays = HandlerRegistry(), []

    @reg.handler("t.flaky")
    async def flaky(ctx, payload):
        raise RuntimeError("slack 503")

    def no_wait(attempt: int) -> int:
        delays.append(attempt)
        return 0

    job_id = await _enqueue(db, "t.flaky", max_attempts=3)
    worker = Worker(db, None, registry=reg, retry_delay=no_wait)
    assert [(await worker.run_once()).outcome for _ in range(3)] == ["retry", "retry", "dead"]
    assert delays == [1, 2] and await worker.run_once() is None
    row = await _job(db, job_id)
    assert (row["done"], row["attempts"]) == (False, 3) and "RuntimeError: slack 503" in row["last_error"]


async def test_a_retry_waits_for_its_backoff(db):
    reg = HandlerRegistry()

    @reg.handler("t.flaky")
    async def flaky(ctx, payload):
        raise RuntimeError("503")

    job_id = await _enqueue(db, "t.flaky")
    worker = Worker(db, None, registry=reg, retry_delay=lambda n: 3600)
    assert (await worker.run_once()).outcome == "retry"
    assert await worker.run_once() is None                    # not due for an hour
    async with db.connection() as c:
        wait = (await (await c.execute("select run_at - now() as wait from jobs where id = %s",
                                       (job_id,))).fetchone())["wait"]
    assert 3500 < wait.total_seconds() <= 3600


async def test_permanent_errors_go_dead_at_once(db):
    reg = HandlerRegistry()

    @reg.handler("t.bad")
    async def bad(ctx, payload):
        raise PermanentJobError("payload has no run_id")

    job_id = await _enqueue(db, "t.bad", max_attempts=5)
    worker = Worker(db, None, registry=reg, retry_delay=lambda n: 0)
    out = await worker.run_once()
    assert out.outcome == "dead" and "no run_id" in out.error
    assert await worker.run_once() is None
    row = await _job(db, job_id)
    assert (row["done"], row["attempts"], row["max_attempts"]) == (False, 5, 5)


async def test_a_handler_that_overruns_is_stopped_and_retried(db):
    reg = HandlerRegistry()

    @reg.handler("t.slow")
    async def slow(ctx, payload):
        await asyncio.sleep(5)

    await _enqueue(db, "t.slow")
    out = await Worker(db, None, registry=reg, lease_s=1, timeout_s=0.05, retry_delay=lambda n: 0).run_once()
    assert out.outcome == "retry" and "timed out" in out.error


async def test_a_leased_job_is_not_run_by_a_second_worker(db):
    reg, started, release = HandlerRegistry(), asyncio.Event(), asyncio.Event()

    @reg.handler("t.block")
    async def block(ctx, payload):
        started.set()
        await release.wait()

    await _enqueue(db, "t.block")
    first = asyncio.create_task(Worker(db, None, registry=reg).run_once())
    await asyncio.wait_for(started.wait(), 5)
    assert await Worker(db, None, registry=reg).run_once() is None
    release.set()
    assert (await first).outcome == "done"


async def test_stop_lets_the_current_job_finish_then_the_loop_exits(db):
    reg, started, release = HandlerRegistry(), asyncio.Event(), asyncio.Event()

    @reg.handler("t.block")
    async def block(ctx, payload):
        started.set()
        await release.wait()

    job_id = await _enqueue(db, "t.block")
    worker = Worker(db, None, registry=reg, poll_s=0.01)
    loop = asyncio.create_task(worker.run())
    await asyncio.wait_for(started.wait(), 5)
    worker.stop()
    release.set()
    await asyncio.wait_for(loop, 5)
    assert (await _job(db, job_id))["done"]


async def test_an_idle_worker_stops_promptly(db):
    worker = Worker(db, None, registry=HandlerRegistry(), poll_s=30)
    loop = asyncio.create_task(worker.run())
    await asyncio.sleep(0.05)
    worker.stop()
    await asyncio.wait_for(loop, 2)

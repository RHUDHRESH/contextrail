"""Every model call leaves a row in llm_calls (T115, CLAUDE.md §11): tier, tokens, cost, latency, outcome.
Real PostgreSQL (migrated_db), fake model clients."""

from decimal import Decimal

import pytest
from llm_fakes import FakeClient, MemoryLedger, Sleeps, api_error, config, make_router, message

from contextrail import repo
from contextrail.db import Database
from contextrail.llm.ledger import LLMLedger
from contextrail.llm.router import LLMCallError, ReplayMiss

USER = [{"role": "user", "content": "hi"}]


@pytest.fixture
async def db(migrated_db):
    d = Database(migrated_db, max_size=2)
    await d.open()
    yield d
    await d.close()


@pytest.fixture
async def run_id(db):
    async with db.transaction() as c:
        row = await repo.create_run(c, source="slack", request_text="Give Anil the same access as Rahul")
    return row["id"]


async def _rows(db) -> list[dict]:
    async with db.connection() as c:
        cur = await c.execute("select * from llm_calls order by id")
        return await cur.fetchall()


async def test_a_failover_then_success_writes_one_row_per_attempt(db, run_id):
    t1 = FakeClient(api_error(529, error_type="overloaded_error"))
    t2 = FakeClient(message("ok", input_tokens=1_000, output_tokens=200))
    router = make_router(config(keys="AB"), {"T1": t1, "T2": t2}, ledger=LLMLedger(db))
    r = await router.call(system="s", messages=USER, max_tokens=50, run_id=run_id, stage="discover")
    assert r.cost_usd == Decimal("0.002000")

    first, second = await _rows(db)
    assert (first["tier"], first["outcome"], first["error"], first["cost_usd"]) == (
        "T1", "failover", "OverloadedError 529", Decimal(0))
    assert first["input_tokens"] is None and first["latency_ms"] >= 0
    assert (second["tier"], second["outcome"], second["model"], second["replay"]) == (
        "T2", "ok", "claude-haiku-4-5-20251001", False)
    assert (second["input_tokens"], second["output_tokens"], second["cost_usd"]) == (1_000, 200, Decimal("0.002000"))
    assert second["latency_ms"] >= 0 and second["error"] is None
    assert {x["run_id"] for x in (first, second)} == {run_id} and {x["stage"] for x in (first, second)} == {"discover"}


async def test_bedrock_rows_name_the_profile_and_are_priced_as_haiku(db, run_id):
    t3 = FakeClient(message("ok", input_tokens=500, output_tokens=100))
    router = make_router(config(keys="", bedrock=True), {"T3": t3}, ledger=LLMLedger(db))
    await router.call(system="s", messages=USER, max_tokens=50, run_id=run_id, stage="plan")
    (row,) = await _rows(db)
    assert (row["tier"], row["model"], row["cost_usd"]) == (
        "T3", "global.anthropic.claude-haiku-4-5-20251001-v1:0", Decimal("0.001000"))


async def test_input_tokens_include_cache_writes_and_reads_and_cost_prices_each(db, run_id):
    t1 = FakeClient(message("ok", input_tokens=40, output_tokens=10, cache_creation_input_tokens=4_000,
                            cache_read_input_tokens=0))
    await make_router(config(keys="A"), {"T1": t1}, ledger=LLMLedger(db)).call(
        system="s", messages=USER, max_tokens=50, run_id=run_id)
    (row,) = await _rows(db)
    assert row["input_tokens"] == 4_040
    assert row["cost_usd"] == Decimal("0.005090")  # 40*1 + 10*5 + 4000*1.25 per million


async def test_a_retried_429_is_its_own_row(db, run_id):
    t1 = FakeClient(api_error(429, headers={"retry-after": "0"}), message("ok"))
    await make_router(config(keys="A"), {"T1": t1}, ledger=LLMLedger(db), sleep=Sleeps()).call(
        system="s", messages=USER, max_tokens=50, run_id=run_id)
    assert [(x["tier"], x["outcome"], x["error"]) for x in await _rows(db)] == [
        ("T1", "error", "RateLimitError 429 (retried)"), ("T1", "ok", None)]


async def test_a_fatal_error_is_an_error_row(db, run_id):
    t1 = FakeClient(api_error(400, "bad"))
    with pytest.raises(LLMCallError):
        await make_router(config(keys="A"), {"T1": t1}, ledger=LLMLedger(db)).call(
            system="s", messages=USER, max_tokens=50, run_id=run_id)
    assert [(x["tier"], x["outcome"], x["error"]) for x in await _rows(db)] == [("T1", "error", "BadRequestError 400")]


async def test_replay_rows_are_flagged_and_free(db, run_id, tmp_path):
    await make_router(config(keys="A", replay="record", llm_replay_dir=str(tmp_path)),
                      {"T1": FakeClient(message("ok", input_tokens=300, output_tokens=30))}).call(
        system="s", messages=USER, max_tokens=50)
    replayer = make_router(config(keys="", replay="replay", llm_replay_dir=str(tmp_path)), {}, ledger=LLMLedger(db))
    await replayer.call(system="s", messages=USER, max_tokens=50, run_id=run_id)
    with pytest.raises(ReplayMiss):
        await replayer.call(system="s", messages=[{"role": "user", "content": "unrecorded"}], max_tokens=50,
                            run_id=run_id)
    hit, miss = await _rows(db)
    assert (hit["tier"], hit["replay"], hit["outcome"], hit["cost_usd"]) == ("T4", True, "ok", Decimal(0))
    assert (hit["input_tokens"], hit["output_tokens"]) == (300, 30)
    assert (miss["tier"], miss["replay"], miss["outcome"], miss["error"]) == ("T4", True, "error", "ReplayMiss")


async def test_calls_outside_a_run_are_logged_without_a_run_id(db):
    await make_router(config(keys="A"), {"T1": FakeClient(message("ok"))}, ledger=LLMLedger(db)).call(
        system="s", messages=USER, max_tokens=50)
    (row,) = await _rows(db)
    assert row["run_id"] is None and row["stage"] is None


async def test_breaker_skips_are_not_calls():
    ledger = MemoryLedger()
    router = make_router(config(keys="AB"), {"T1": FakeClient(api_error(500)),
                                             "T2": FakeClient(message("a"), message("b"))}, ledger=ledger)
    await router.call(system="s", messages=USER, max_tokens=50)
    await router.call(system="s", messages=USER, max_tokens=50)   # T1 skipped by its open breaker: no row
    assert [(x["tier"], x["outcome"]) for x in ledger.rows] == [("T1", "failover"), ("T2", "ok"), ("T2", "ok")]


def test_the_router_cannot_be_built_without_a_ledger():
    from contextrail.llm.router import Router

    with pytest.raises(TypeError):
        Router(config(keys="A"), {})  # no ledger, no router: every call must be logged

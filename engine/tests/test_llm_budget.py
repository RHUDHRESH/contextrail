"""Budgets (T116, CLAUDE.md §11, D-013): a per-run cap (RUN_BUDGET_USD, $0.50) and a hard Bedrock cap
(BEDROCK_BUDGET_USD, $20). Refusals are logged as outcome 'budget_refused'. Real PostgreSQL, fake model clients."""

import asyncio
import time
from decimal import Decimal

import pytest
from llm_fakes import FakeClient, config, make_router, message

from contextrail import repo
from contextrail.db import Database
from contextrail.llm.ledger import LLMLedger
from contextrail.llm.router import BudgetExceeded, LLMError, NoTierAvailable

USER = [{"role": "user", "content": "hi"}]


@pytest.fixture
async def db(migrated_db):
    d = Database(migrated_db, max_size=2)
    await d.open()
    yield d
    await d.close()


async def _run(db) -> object:
    async with db.transaction() as c:
        return (await repo.create_run(c, source="slack", request_text="req"))["id"]


async def _spent(db, *, run_id=None, tier="T1", cost: str) -> None:
    async with db.connection() as c:
        await c.execute("insert into llm_calls (run_id, model, tier, cost_usd) values (%s, %s, %s, %s)",
                        (run_id, "claude-haiku-4-5-20251001", tier, Decimal(cost)))


async def _rows(db, outcome: str) -> list[dict]:
    async with db.connection() as c:
        cur = await c.execute("select * from llm_calls where outcome = %s order by id", (outcome,))
        return await cur.fetchall()


async def test_a_run_at_its_cap_is_refused_before_any_model_call(db):
    run = await _run(db)
    await _spent(db, run_id=run, cost="0.499")
    t1 = FakeClient()
    router = make_router(config(keys="A"), {"T1": t1}, ledger=LLMLedger(db))
    # worst case for 300 output tokens is $0.0015; 0.499 + 0.0015 > 0.50
    with pytest.raises(BudgetExceeded, match="0.50"):
        await router.call(system="s", messages=USER, max_tokens=300, run_id=run, stage="plan")
    assert t1.calls == []
    (row,) = await _rows(db, "budget_refused")
    assert (row["run_id"], row["tier"], row["stage"], row["cost_usd"]) == (run, "T1", "plan", Decimal(0))
    assert "0.499" in row["error"]


async def test_a_run_under_its_cap_proceeds(db):
    run = await _run(db)
    await _spent(db, run_id=run, cost="0.10")
    router = make_router(config(keys="A"), {"T1": FakeClient(message("ok"))}, ledger=LLMLedger(db))
    assert (await router.call(system="s", messages=USER, max_tokens=300, run_id=run)).text == "ok"


async def test_the_cap_is_per_run(db):
    busy, fresh = await _run(db), await _run(db)
    await _spent(db, run_id=busy, cost="0.50")
    router = make_router(config(keys="A"), {"T1": FakeClient(message("ok"))}, ledger=LLMLedger(db))
    assert (await router.call(system="s", messages=USER, max_tokens=100, run_id=fresh)).text == "ok"


async def test_the_run_cap_comes_from_settings(db):
    run = await _run(db)
    await _spent(db, run_id=run, cost="0.05")
    router = make_router(config(keys="A", run_budget_usd=Decimal("0.05")), {"T1": FakeClient()}, ledger=LLMLedger(db))
    with pytest.raises(BudgetExceeded):
        await router.call(system="s", messages=USER, max_tokens=10, run_id=run)


async def test_budget_refusal_is_an_llm_error_so_callers_fall_back():
    assert issubclass(BudgetExceeded, LLMError)


def test_the_bedrock_cap_cannot_be_raised_by_configuration():
    assert config(keys="", bedrock=True, bedrock_budget_usd=Decimal(200)).bedrock_budget_usd == Decimal(20)


async def test_bedrock_at_its_20_dollar_cap_is_skipped_and_logged(db, tmp_path):
    await _spent(db, tier="T3", cost="19.9999")
    await make_router(config(keys="A", replay="record", llm_replay_dir=str(tmp_path)),
                      {"T1": FakeClient(message("recorded"))}).call(system="s", messages=USER, max_tokens=100)
    t3 = FakeClient()
    router = make_router(config(keys="", bedrock=True, replay="replay", llm_replay_dir=str(tmp_path)),
                         {"T3": t3}, ledger=LLMLedger(db))
    r = await router.call(system="s", messages=USER, max_tokens=100)
    assert (r.tier, r.replay) == ("T4", True)          # the chain went on past the capped tier
    assert t3.calls == []
    (row,) = await _rows(db, "budget_refused")
    assert row["tier"] == "T3" and "20" in row["error"]


async def test_bedrock_cap_with_nothing_after_it_is_no_tier_available(db):
    await _spent(db, tier="T3", cost="20")
    router = make_router(config(keys="", bedrock=True), {"T3": FakeClient()}, ledger=LLMLedger(db))
    with pytest.raises(NoTierAvailable, match="Bedrock cap"):
        await router.call(system="s", messages=USER, max_tokens=100)


async def test_bedrock_under_its_cap_serves_and_other_tiers_spend_does_not_count(db):
    await _spent(db, tier="T1", cost="25")              # direct-API spend is not Bedrock spend
    await _spent(db, tier="T3", cost="5")
    router = make_router(config(keys="", bedrock=True), {"T3": FakeClient(message("ok"))}, ledger=LLMLedger(db))
    assert (await router.call(system="s", messages=USER, max_tokens=100)).tier == "T3"


async def test_replay_is_free_and_never_budget_refused(db, tmp_path):
    run = await _run(db)
    await _spent(db, run_id=run, cost="9.99")
    await make_router(config(keys="A", replay="record", llm_replay_dir=str(tmp_path)),
                      {"T1": FakeClient(message("recorded"))}).call(system="s", messages=USER, max_tokens=100)
    replayer = make_router(config(keys="", replay="replay", llm_replay_dir=str(tmp_path)), {}, ledger=LLMLedger(db))
    assert (await replayer.call(system="s", messages=USER, max_tokens=100, run_id=run)).replay is True


async def test_ledger_spend_queries(db):
    run = await _run(db)
    await _spent(db, run_id=run, cost="0.1")
    await _spent(db, run_id=run, tier="T3", cost="0.2")
    await _spent(db, tier="T3", cost="0.3")
    ledger = LLMLedger(db)
    assert await ledger.run_spend(run) == Decimal("0.3")
    assert await ledger.tier_spend("T3") == Decimal("0.5")
    assert await ledger.tier_spend("T2") == Decimal(0)


async def test_two_routers_cannot_charge_the_same_run_past_its_cap(db):
    run = await _run(db)

    class SlowClient(FakeClient):
        def create(self, **kwargs):
            time.sleep(0.05)
            return super().create(**kwargs)

    clients = [SlowClient(message("ok", input_tokens=900, output_tokens=100)) for _ in range(2)]
    routers = [make_router(config(keys="A", run_budget_usd=Decimal("0.003")), {"T1": client},
                           ledger=LLMLedger(db)) for client in clients]
    results = await asyncio.gather(*(router.call(system="s", messages=USER, max_tokens=100, run_id=run)
                                     for router in routers), return_exceptions=True)
    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert sum(isinstance(result, BudgetExceeded) for result in results) == 1
    assert sum(len(client.calls) for client in clients) == 1
    assert await LLMLedger(db).run_spend(run) == Decimal("0.001400")

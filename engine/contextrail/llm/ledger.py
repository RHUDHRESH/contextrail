"""The llm_calls ledger (T115, CLAUDE.md §11): one row per model call attempt, written outside any stage transaction.

Money spent stays recorded even if the stage that asked for the call rolls back. Columns come from
migrations/0002_audit_jobs_llm.sql. `input_tokens` is the whole prompt (uncached + cache-write + cache-read tokens);
`cost_usd` prices each part at its own rate (llm/pricing.py).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from decimal import Decimal
from uuid import UUID

from psycopg import AsyncConnection

from contextrail.db import Database

_BUDGET_LOCK_NAMESPACE = 0x4352  # ContextRail; two-key PostgreSQL advisory lock namespace.
_BEDROCK_LOCK = 0


class LLMLedger:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._guard_connection: ContextVar[AsyncConnection | None] = ContextVar("llm_budget_connection", default=None)

    @asynccontextmanager
    async def budget_guard(self, run_id: UUID | None, tier: str) -> AsyncIterator[None]:
        """Serialize a live call with others charging the same run or Bedrock account.

        The session lock covers the spend check, model call, and ledger write. Each model call uses its own pooled
        connection so one stalled request cannot hold a stage transaction open. A guard's ledger operations use
        that same connection, allowing even a one-connection pool to log its attempt before releasing the lock.
        """
        keys = ([_BEDROCK_LOCK] if tier == "T3" else []) + ([run_id.int % (2**31 - 1) + 1] if run_id else [])
        if not keys:
            yield
            return
        async with self.db.connection() as conn:
            acquired: list[int] = []
            token = self._guard_connection.set(conn)
            try:
                for key in keys:
                    await conn.execute("select pg_advisory_lock(%s, %s)", (_BUDGET_LOCK_NAMESPACE, key))
                    acquired.append(key)
                yield
            finally:
                try:
                    for key in reversed(acquired):
                        await conn.execute("select pg_advisory_unlock(%s, %s)", (_BUDGET_LOCK_NAMESPACE, key))
                finally:
                    self._guard_connection.reset(token)

    async def run_spend(self, run_id: UUID) -> Decimal:
        return await self._spend("where run_id = %s", (run_id,))

    async def tier_spend(self, tier: str) -> Decimal:
        return await self._spend("where tier = %s", (tier,))

    async def _spend(self, where: str, params: tuple) -> Decimal:
        conn = self._guard_connection.get()
        if conn is None:
            async with self.db.connection() as conn:
                return await self._sum(conn, where, params)
        return await self._sum(conn, where, params)

    @staticmethod
    async def _sum(conn: AsyncConnection, where: str, params: tuple) -> Decimal:
        row = await (await conn.execute(f"select coalesce(sum(cost_usd), 0) as spent from llm_calls {where}",
                                      params)).fetchone()
        return row["spent"]

    async def record(self, *, run_id: UUID | None, stage: str | None, model: str, tier: str, replay: bool,
                     input_tokens: int | None, output_tokens: int | None, cost_usd: Decimal, latency_ms: int,
                     outcome: str, error: str | None) -> None:
        conn = self._guard_connection.get()
        if conn is None:
            async with self.db.connection() as conn:
                await self._insert(conn, run_id, stage, model, tier, replay, input_tokens, output_tokens,
                                   cost_usd, latency_ms, outcome, error)
        else:
            await self._insert(conn, run_id, stage, model, tier, replay, input_tokens, output_tokens,
                               cost_usd, latency_ms, outcome, error)

    @staticmethod
    async def _insert(conn: AsyncConnection, run_id: UUID | None, stage: str | None, model: str, tier: str,
                      replay: bool, input_tokens: int | None, output_tokens: int | None, cost_usd: Decimal,
                      latency_ms: int, outcome: str, error: str | None) -> None:
        await conn.execute(
            """insert into llm_calls (run_id, stage, model, tier, replay, input_tokens, output_tokens, cost_usd,
                                      latency_ms, outcome, error)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (run_id, stage, model, tier, replay, input_tokens, output_tokens, cost_usd, latency_ms, outcome,
             error))

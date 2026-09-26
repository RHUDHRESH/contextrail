"""The llm_calls ledger (T115, CLAUDE.md §11): one row per model call attempt, written outside any stage transaction.

Money spent stays recorded even if the stage that asked for the call rolls back. Columns come from
migrations/0002_audit_jobs_llm.sql. `input_tokens` is the whole prompt (uncached + cache-write + cache-read tokens);
`cost_usd` prices each part at its own rate (llm/pricing.py).
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from contextrail.db import Database


class LLMLedger:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def record(self, *, run_id: UUID | None, stage: str | None, model: str, tier: str, replay: bool,
                     input_tokens: int | None, output_tokens: int | None, cost_usd: Decimal, latency_ms: int,
                     outcome: str, error: str | None) -> None:
        async with self.db.connection() as c:
            await c.execute(
                """insert into llm_calls (run_id, stage, model, tier, replay, input_tokens, output_tokens, cost_usd,
                                          latency_ms, outcome, error)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (run_id, stage, model, tier, replay, input_tokens, output_tokens, cost_usd, latency_ms, outcome,
                 error))

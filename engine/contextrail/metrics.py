"""Operational metrics (checklist T214, CLAUDE.md §17): counted from the tables at request time, never estimated.

- runs: total, by status, by source (door)
- verdicts: actions by ALLOW / HOLD / REFUSE
- time to access: median seconds from a run's creation to each verified grant (held grants include the wait for
  their approver, which is the honest number)
- LLM: calls, replayed calls, cost by tier (llm_calls, written by the router)
- decisions per door (approvals.channel)
"""

from __future__ import annotations

from decimal import Decimal

from psycopg import AsyncConnection
from pydantic import BaseModel, ConfigDict


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunCounts(_M):
    total: int
    by_status: dict[str, int]
    by_source: dict[str, int]


class TimeToAccess(_M):
    median: float | None      # seconds; None until a grant has been verified
    count: int


class LlmSpend(_M):
    calls: int
    replay_calls: int
    cost_usd_by_tier: dict[str, Decimal]


class Metrics(_M):
    runs: RunCounts
    verdicts: dict[str, int]
    time_to_access_s: TimeToAccess
    llm: LlmSpend
    decisions_by_door: dict[str, int]


async def collect(conn: AsyncConnection) -> Metrics:
    async def rows(sql: str) -> list[dict]:
        return await (await conn.execute(sql)).fetchall()

    by_status: dict[str, int] = {}
    by_source: dict[str, int] = {}
    for r in await rows("select status, source, count(*) as n from runs group by status, source"):
        by_status[r["status"]] = by_status.get(r["status"], 0) + r["n"]
        by_source[r["source"]] = by_source.get(r["source"], 0) + r["n"]
    verdicts = {"ALLOW": 0, "HOLD": 0, "REFUSE": 0}
    verdicts.update({r["verdict"]: r["n"] for r in await rows(
        "select verdict, count(*) as n from actions group by verdict")})
    tta = (await rows("""
        select percentile_cont(0.5) within group (order by extract(epoch from a.verified_at - r.created_at)::float8)
                   as median, count(*) as n
        from actions a join runs r on r.id = a.run_id
        where a.kind = 'grant' and a.state = 'verified'"""))[0]
    llm = await rows("select tier, count(*) as calls, count(*) filter (where replay) as replays, "
                     "sum(cost_usd) as cost from llm_calls group by tier order by tier")
    doors = await rows("select channel, count(*) as n from approvals group by channel order by channel")
    return Metrics(
        runs=RunCounts(total=sum(by_status.values()), by_status=dict(sorted(by_status.items())),
                       by_source=dict(sorted(by_source.items()))),
        verdicts=verdicts,
        time_to_access_s=TimeToAccess(median=tta["median"], count=tta["n"]),
        llm=LlmSpend(calls=sum(r["calls"] for r in llm), replay_calls=sum(r["replays"] for r in llm),
                     cost_usd_by_tier={r["tier"]: r["cost"] for r in llm}),
        decisions_by_door={r["channel"]: r["n"] for r in doors})

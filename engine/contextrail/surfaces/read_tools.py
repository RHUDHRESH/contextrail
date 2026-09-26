"""Read-only providers for the bounded question agent.

Personal run reads are scoped to the resolved actor before any status is loaded. Knowledge reads use the indexed
OKF bundle and cite its chunks; precedents come only from the verified audit chain.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from contextrail.knowledge.precedent import ChainBroken, compute_precedents
from contextrail.knowledge.rag import answer as answer_from_knowledge
from contextrail.llm.question_agent import NO_SUPPORT, ReadEvidence

if TYPE_CHECKING:
    from contextrail.surfaces.door import Door


def _unsupported(kind: str) -> ReadEvidence:
    return ReadEvidence(text=NO_SUPPORT, citations=[], supported=False, kind=kind)


class PlatformReadTools:
    def __init__(self, door: Door) -> None:
        self.door = door

    async def search_knowledge(self, query: str, *, actor_id: str | None) -> ReadEvidence:
        # The question agent spends its own capped model budget choosing tools. Extractive RAG cannot introduce
        # ungrounded prose or a second unbudgeted model call.
        async with self.door.db.connection() as conn:
            found = await answer_from_knowledge(conn, query, model=None)
        return ReadEvidence(text=found.text, citations=[*found.chunk_ids,
            *(f"audit:{seq}" for seq in found.audit_seqs)], supported=found.supported, kind="knowledge")

    async def run_status(self, run_id: UUID, *, actor_id: str) -> ReadEvidence:
        async with self.door.db.connection() as conn:
            owned = await (await conn.execute(
                "select id from runs where id = %s and requested_by = %s", (run_id, actor_id))).fetchone()
            if owned is None:
                return _unsupported("run")
            rows = await (await conn.execute(
                "select seq from audit where run_id = %s and event like 'stage.%%' order by seq desc limit 1",
                (run_id,))).fetchall()
        if not rows:
            return _unsupported("run")
        view = await self.door.get_status(run_id)
        waiting = [r.approver_name or r.approver_id for r in view.rows if r.state == "awaiting"]
        text = (f"Run {run_id} is {view.status.replace('_', ' ')}: "
                f"{view.counts['verified']} verified, {view.counts['awaiting']} awaiting approval, "
                f"{view.counts['refuse']} refused.")
        if waiting:
            text += f" Waiting for {', '.join(str(name) for name in waiting)}."
        return ReadEvidence(text=text, citations=[f"audit:{rows[0]['seq']}"], supported=True, kind="run")

    async def my_runs(self, limit: int, *, actor_id: str) -> ReadEvidence:
        async with self.door.db.connection() as conn:
            rows = await (await conn.execute("""
                select r.id, r.status, a.seq from runs r
                left join lateral (select seq from audit where run_id = r.id order by seq desc limit 1) a on true
                where r.requested_by = %s order by r.created_at desc, r.id desc limit %s
                """, (actor_id, limit))).fetchall()
        cited = [row for row in rows if row["seq"] is not None]
        if not cited:
            return _unsupported("run")
        text = "Your runs: " + "; ".join(f"{row['id']} ({row['status'].replace('_', ' ')})" for row in cited) + "."
        return ReadEvidence(text=text, citations=[f"audit:{row['seq']}" for row in cited],
                            supported=True, kind="run")

    async def precedents(self, rule_id: str, *, actor_id: str | None) -> ReadEvidence:
        try:
            async with self.door.db.connection() as conn:
                book = await compute_precedents(conn)
        except ChainBroken:
            return _unsupported("precedent")
        entries = [entry for entry in book.entries.values() if entry.rule_id == rule_id and entry.cites]
        if not entries:
            return _unsupported("precedent")
        text = (f"Verified audit precedents for {rule_id}: " + "; ".join(
            f"{entry.entitlement}: {entry.approved} approved, {entry.refused} refused" for entry in entries) + ".")
        return ReadEvidence(text=text, citations=[f"audit:{seq}" for entry in entries for seq in entry.cites],
                            supported=True, kind="precedent")

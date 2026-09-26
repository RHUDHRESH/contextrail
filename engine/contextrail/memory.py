"""Expiring conversation pointers for a door thread (T251).

Only a resolved person may have memory. This is context for finding a run, never
an instruction or an authority for a decision. Callers store short summaries,
not the inbound text. Read results carry an audit/run citation and must be
resolved against the authoritative run before answering.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from contextrail.db import Database

MAX_ENTRIES = 20
MAX_SUMMARY = 512
RETENTION = timedelta(days=30)

_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{7,}\d(?!\w)")
_SECRET = re.compile(r"(?i)\b(?:fwapi_[A-Za-z0-9_-]+|(?:api[_ -]?key|bearer|token|password)\s*[:= ]\s*[^\s,;]+)")


def redact_summary(value: str) -> str:
    """Defence in depth; door hooks pass fixed summaries with no user text."""
    clean = _SECRET.sub("[redacted]", value)
    clean = _EMAIL.sub("[email]", clean)
    clean = _PHONE.sub("[phone]", clean)
    return clean[:MAX_SUMMARY]


def thread_key(thread_ref: str) -> str:
    """Avoid storing ticket, call, or message IDs in clear text."""
    if not thread_ref:
        raise ValueError("thread_ref is required")
    return hashlib.sha256(thread_ref.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MemoryEntry:
    role: str
    summary: str
    run_id: UUID | None
    audit_seqs: tuple[int, ...]
    source: str


class ConversationMemory:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def append(self, *, channel: str, person_id: str, thread_ref: str, role: str, summary: str,
                     run_id: UUID | None, audit_seqs: tuple[int, ...] = ()) -> None:
        if role not in ("user", "assistant"):
            raise ValueError("role must be user or assistant")
        if not person_id or run_id is None:
            raise ValueError("resolved person and cited run are required")
        key = thread_key(thread_ref)
        # Serialize this scope's insert and cap even for simultaneous door events.
        lock = int.from_bytes(hashlib.sha256(f"{channel}:{person_id}:{key}".encode()).digest()[:8], "big", signed=True)
        async with self.db.transaction() as c:
            await c.execute("select pg_advisory_xact_lock(%s)", (lock,))
            await c.execute("delete from conversation_memory where expires_at <= now()")
            await c.execute(
                """insert into conversation_memory
                   (channel, person_id, thread_key, role, summary, run_id, audit_seqs, expires_at)
                   values (%s, %s, %s, %s, %s, %s, %s, now() + interval '30 days')""",
                (channel, person_id, key, role, redact_summary(summary), run_id, list(audit_seqs)),
            )
            await c.execute(
                """delete from conversation_memory where id in (
                     select id from conversation_memory
                     where channel = %s and person_id = %s and thread_key = %s
                     order by id desc offset %s)""",
                (channel, person_id, key, MAX_ENTRIES),
            )

    async def recent(self, *, channel: str, person_id: str, thread_ref: str,
                     limit: int = MAX_ENTRIES) -> list[MemoryEntry]:
        if not person_id:
            return []
        key = thread_key(thread_ref)
        async with self.db.connection() as c:
            rows = await (await c.execute(
                """select role, summary, run_id, audit_seqs from conversation_memory
                   where channel = %s and person_id = %s and thread_key = %s and expires_at > now()
                   order by id desc limit %s""",
                (channel, person_id, key, max(1, min(limit, MAX_ENTRIES))),
            )).fetchall()
        return [MemoryEntry(role=r["role"], summary=r["summary"], run_id=r["run_id"],
                            audit_seqs=tuple(r["audit_seqs"]),
                            source=f"run:{r['run_id']}" + (f"#audit:{','.join(map(str, r['audit_seqs']))}"
                                                     if r["audit_seqs"] else "")) for r in reversed(rows)]

    async def forget(self, *, channel: str, person_id: str, thread_ref: str) -> int:
        """Delete a single actor's thread, for privacy and retention controls."""
        if not person_id:
            return 0
        async with self.db.transaction() as c:
            cursor = await c.execute(
                "delete from conversation_memory where channel = %s and person_id = %s and thread_key = %s",
                (channel, person_id, thread_key(thread_ref)),
            )
            return cursor.rowcount

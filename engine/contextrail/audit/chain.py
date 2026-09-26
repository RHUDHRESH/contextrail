"""The audit hash chain (checklist T209).

    hash = sha256(prev_hash || canonical_json({"event": event, "payload": payload, "at": at}))

The first row's prev_hash is "GENESIS". The database already refuses UPDATE/DELETE/TRUNCATE on `audit`
(0002). The chain is the second line of defence: if someone removes the trigger and edits a row, every later hash
stops matching, and `verify_chain` names the first broken row.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from psycopg import AsyncConnection

from contextrail import repo
from contextrail.canonical import canonical_json

GENESIS = repo.GENESIS


def chain_hash(prev_hash: str, event: str, payload: dict, at: datetime) -> str:
    body = canonical_json({"event": event, "payload": payload, "at": at})
    return hashlib.sha256((prev_hash + body).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ChainCheck:
    ok: bool
    rows: int
    first_broken_seq: int | None = None
    reason: str | None = None


def verify_chain(rows: Iterable[dict[str, Any]]) -> ChainCheck:
    """Rows in seq order with prev_hash, hash, event, payload, at. Recomputes every link."""
    prev = GENESIS
    n = 0
    for row in rows:
        n += 1
        if row["prev_hash"] != prev:
            return ChainCheck(False, n, row["seq"], "prev_hash does not match the previous row's hash")
        if chain_hash(row["prev_hash"], row["event"], row["payload"], row["at"]) != row["hash"]:
            return ChainCheck(False, n, row["seq"], "row content does not match its hash")
        prev = row["hash"]
    return ChainCheck(True, n)


async def append(conn: AsyncConnection, *, run_id, event: str, payload: dict) -> dict:
    """Append one event to the global chain. Must run inside a transaction (repo.append_audit enforces it)."""
    return await repo.append_audit(conn, run_id=run_id, event=event, payload=payload, hash_fn=chain_hash)


async def verify_db(conn: AsyncConnection) -> ChainCheck:
    cur = await conn.execute("select seq, prev_hash, hash, event, payload, at from audit order by seq")
    return verify_chain(await cur.fetchall())

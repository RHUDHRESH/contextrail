"""Repository functions over the schema (checklist T042). Storage only: no policy, no model calls.

Every function takes an open connection, so callers choose the unit of work:
`async with db.transaction() as c: await upsert_action(c, ...); await append_audit(c, ...)`.

Concurrency rules encoded here:
- `record_approval` returns False when another door already decided (first decision wins, D-005).
- `claim_job` uses `FOR UPDATE SKIP LOCKED` with a lease, so two workers never run the same job, and a crashed
  worker's job becomes claimable again once its lease expires (D-003).
- `append_audit` takes a transaction-scoped advisory lock, so concurrent writers extend one linear hash chain
  instead of forking it (P7). The hash itself is computed by the caller's `hash_fn` (audit/chain.py, T209).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

GENESIS = "GENESIS"
_AUDIT_LOCK_KEY = 7_214_119_002

HashFn = Callable[[str, str, dict, datetime], str]


async def _one(conn: AsyncConnection, sql: str, params: Iterable[Any] = ()) -> dict | None:
    cur = await conn.execute(sql, tuple(params))
    return await cur.fetchone()


# --- runs --------------------------------------------------------------------------------------------------

async def create_run(conn: AsyncConnection, *, source: str, request_text: str, source_ref: str | None = None,
                     requested_by: str | None = None, run_id: uuid.UUID | None = None) -> dict:
    return await _one(conn, """
        insert into runs (id, source, source_ref, request_text, requested_by)
        values (%s, %s, %s, %s, %s) returning *""",
        (run_id or uuid.uuid4(), source, source_ref, request_text, requested_by))


async def get_run(conn: AsyncConnection, run_id: uuid.UUID) -> dict | None:
    return await _one(conn, "select * from runs where id = %s", (run_id,))


async def set_stage(conn: AsyncConnection, run_id: uuid.UUID, *, stage: str | None = None,
                    status: str | None = None, **fields: Any) -> dict:
    """Update stage/status and optional run fields (intent, subject_id, capsule, capsule_digest).

    Transition legality is checked by the rail (models, T052); this layer only persists.
    """
    allowed = {"intent", "subject_id", "capsule", "capsule_digest"}
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"set_stage: unknown run fields {sorted(unknown)}")
    sets, params = ["updated_at = now()"], []
    for col, val in (("stage", stage), ("status", status), *fields.items()):
        if val is None and col in ("stage", "status"):
            continue
        sets.append(f"{col} = %s")
        params.append(Jsonb(val) if col == "capsule" and val is not None else val)
    row = await _one(conn, f"update runs set {', '.join(sets)} where id = %s returning *", (*params, run_id))
    if row is None:
        raise LookupError(f"run {run_id} not found")
    return row


# --- actions -----------------------------------------------------------------------------------------------

async def upsert_action(conn: AsyncConnection, run_id: uuid.UUID, *, id: str, kind: str, target: dict,
                        params_hash: str, verdict: str, rule_id: str, clause: str, approver: str | None = None,
                        state: str = "planned", idempotency_key: str | None = None, evidence: Any = None,
                        expires_at: datetime | None = None) -> dict:
    return await _one(conn, """
        insert into actions (id, run_id, kind, target, params_hash, verdict, rule_id, clause, approver, state,
                             idempotency_key, evidence, expires_at)
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        on conflict (run_id, id) do update set
            kind = excluded.kind, target = excluded.target, params_hash = excluded.params_hash,
            verdict = excluded.verdict, rule_id = excluded.rule_id, clause = excluded.clause,
            approver = excluded.approver, state = excluded.state, idempotency_key = excluded.idempotency_key,
            evidence = excluded.evidence, expires_at = excluded.expires_at, updated_at = now()
        returning *""",
        (id, run_id, kind, Jsonb(target), params_hash, verdict, rule_id, clause, approver, state,
         idempotency_key, Jsonb(evidence) if evidence is not None else None, expires_at))


async def set_action_state(conn: AsyncConnection, run_id: uuid.UUID, action_id: str, state: str, *,
                           verified_at: datetime | None = None) -> dict:
    row = await _one(conn, """
        update actions set state = %s, verified_at = coalesce(%s, verified_at), updated_at = now()
        where run_id = %s and id = %s returning *""", (state, verified_at, run_id, action_id))
    if row is None:
        raise LookupError(f"action {run_id}/{action_id} not found")
    return row


async def list_actions(conn: AsyncConnection, run_id: uuid.UUID) -> list[dict]:
    cur = await conn.execute("select * from actions where run_id = %s order by created_at, id", (run_id,))
    return await cur.fetchall()


# --- approvals ---------------------------------------------------------------------------------------------

async def record_approval(conn: AsyncConnection, run_id: uuid.UUID, action_id: str, *, params_hash: str,
                          approver: str, decision: str, channel: str, reason: str | None = None) -> bool:
    """Insert a decision. Returns True if this call won; False if any door had already decided."""
    row = await _one(conn, """
        insert into approvals (run_id, action_id, params_hash, approver, decision, reason, channel)
        values (%s, %s, %s, %s, %s, %s, %s)
        on conflict (run_id, action_id) do nothing returning run_id""",
        (run_id, action_id, params_hash, approver, decision, reason, channel))
    return row is not None


async def get_approval(conn: AsyncConnection, run_id: uuid.UUID, action_id: str) -> dict | None:
    return await _one(conn, "select * from approvals where run_id = %s and action_id = %s", (run_id, action_id))


# --- audit -------------------------------------------------------------------------------------------------

async def append_audit(conn: AsyncConnection, *, run_id: uuid.UUID | None, event: str, payload: dict,
                       hash_fn: HashFn) -> dict:
    """Append one audit row extending the single global chain. Must run inside a transaction."""
    if conn.info.transaction_status.name == "IDLE":
        raise RuntimeError("append_audit must run inside a transaction (use db.transaction())")
    await conn.execute("select pg_advisory_xact_lock(%s)", (_AUDIT_LOCK_KEY,))
    last = await _one(conn, "select hash from audit order by seq desc limit 1")
    prev_hash = last["hash"] if last else GENESIS
    at = datetime.now(UTC)
    digest = hash_fn(prev_hash, event, payload, at)
    return await _one(conn, """
        insert into audit (run_id, event, payload, prev_hash, hash, at)
        values (%s, %s, %s, %s, %s, %s) returning *""",
        (run_id, event, Jsonb(payload), prev_hash, digest, at))


# --- jobs --------------------------------------------------------------------------------------------------

async def enqueue_job(conn: AsyncConnection, kind: str, payload: dict | None = None, *,
                      run_at: datetime | None = None, dedupe_key: str | None = None,
                      max_attempts: int = 5) -> int | None:
    """Enqueue a job. Returns its id, or None if a job with the same dedupe_key already exists."""
    row = await _one(conn, """
        insert into jobs (kind, payload, run_at, dedupe_key, max_attempts)
        values (%s, %s, coalesce(%s, now()), %s, %s)
        on conflict (dedupe_key) do nothing returning id""",
        (kind, Jsonb(payload or {}), run_at, dedupe_key, max_attempts))
    return row["id"] if row else None


async def claim_job(conn: AsyncConnection, *, kinds: list[str] | None = None, lease_seconds: int = 60) -> dict | None:
    """Claim the next ready job with a lease; concurrent workers skip rows another worker holds."""
    return await _one(conn, """
        update jobs set locked_until = now() + make_interval(secs => %s), attempts = attempts + 1
        where id = (
            select id from jobs
            where not done and run_at <= now()
              and (locked_until is null or locked_until < now())
              and attempts < max_attempts
              and (%s::text[] is null or kind = any(%s::text[]))
            order by run_at, id
            for update skip locked
            limit 1)
        returning *""", (lease_seconds, kinds, kinds))


async def complete_job(conn: AsyncConnection, job_id: int) -> None:
    await conn.execute("update jobs set done = true, locked_until = null, last_error = null where id = %s",
                       (job_id,))


async def fail_job(conn: AsyncConnection, job_id: int, error: str, *, retry_in_seconds: int = 30) -> None:
    await conn.execute("""
        update jobs set locked_until = null, last_error = %s,
                        run_at = now() + make_interval(secs => %s)
        where id = %s""", (error[:2000], retry_in_seconds, job_id))


# --- doors -------------------------------------------------------------------------------------------------

async def upsert_door_message(conn: AsyncConnection, run_id: uuid.UUID, channel: str, ref: dict, *,
                              action_id: str = "") -> dict:
    return await _one(conn, """
        insert into door_messages (run_id, action_id, channel, ref) values (%s, %s, %s, %s)
        on conflict (run_id, action_id, channel) do update set ref = excluded.ref, updated_at = now()
        returning *""", (run_id, action_id, channel, Jsonb(ref)))


async def list_door_messages(conn: AsyncConnection, run_id: uuid.UUID, action_id: str = "") -> list[dict]:
    cur = await conn.execute(
        "select * from door_messages where run_id = %s and action_id = %s order by channel", (run_id, action_id))
    return await cur.fetchall()


async def dedupe_webhook(conn: AsyncConnection, source: str, external_id: str,
                         run_id: uuid.UUID | None = None) -> bool:
    """True on the first delivery of (source, external_id); False on every retry."""
    row = await _one(conn, """
        insert into webhook_dedupe (source, external_id, run_id) values (%s, %s, %s)
        on conflict do nothing returning external_id""", (source, external_id, run_id))
    return row is not None

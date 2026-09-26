"""Receipts (checklist T210, P7 "everything leaves a receipt"): a short human summary and the full JSON of a run.

Built only from stored, code-written facts, never from model output:
- the run row, and every action with its verdict, rule, clause verbatim, state and verified_at (actions table);
- every decision: who, which door, when, for which params_hash (approvals table);
- the evidence ids with their trust labels, and the capsule digest, re-verified against its content (P5);
- this run's audit seq range, and a check of the whole hash chain (audit/chain.verify_db, P7);
- each connector's honest mode (LIVE / FIXTURE / ONE-WAY, D-004), and whether any model output was replayed.

A broken chain or seal is reported in the receipt, in plain words, never hidden.

Idempotent: the digest covers everything except when it was built and the chain check (which changes as other runs
extend the global chain). Rebuilding an unchanged run changes nothing and appends nothing. A new receipt replaces the
stored one and appends 'receipt.built' with its digest to the audit chain, so a later edit of the row is detectable.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from contextrail import repo
from contextrail.audit import chain
from contextrail.canonical import canonical_json, sha256_hex
from contextrail.capsule import DigestMismatch
from contextrail.db import Database
from contextrail.intake import TICKET_CHANNELS, advisory_lock
from contextrail.jobs import PermanentJobError, handler
from contextrail.knowledge.rag import index_receipt
from contextrail.logs import get_logger
from contextrail.rail.store import load_case
from contextrail.surfaces.presenter import LAMP, build_view

log = get_logger("contextrail.receipts")
_EVIDENCE_FIELDS = ("id", "kind", "source", "trust", "stale")
_RUN_FIELDS = ("id", "source", "source_ref", "request_text", "intent", "status", "stage", "requested_by",
               "subject_id", "created_at")
_SHOW = 3  # per summary section; the full list is in the JSON


class Receipt(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: UUID
    digest: str
    summary: str
    body: dict
    audit_from: int | None
    audit_to: int | None
    created: bool  # False when an identical receipt was already stored


async def _facts(conn: AsyncConnection, run_id: UUID) -> dict | None:
    run = await repo.get_run(conn, run_id)
    if run is None:
        return None

    async def rows(sql: str) -> list[dict]:
        return await (await conn.execute(sql, (run_id,))).fetchall()

    audit = (await rows("select min(seq) as from_seq, max(seq) as to_seq, count(*) as events from audit "
                        "where run_id = %s and event not like 'receipt.%%'"))[0]
    llm = (await rows("select count(*) as calls, coalesce(bool_or(replay), false) as replay "
                      "from llm_calls where run_id = %s"))[0]
    if run["capsule"] is None:
        seal = {"digest": None, "seal_verified": None, "problem": "no case file was compiled"}
    else:
        try:
            await load_case(conn, run_id)
            seal = {"digest": run["capsule_digest"], "seal_verified": True, "problem": None}
        except (DigestMismatch, ValidationError, ValueError) as e:
            seal = {"digest": run["capsule_digest"], "seal_verified": False, "problem": str(e)[:300]}
    return {"run": run, "actions": await repo.list_actions(conn, run_id),
            "approvals": await rows("select * from approvals where run_id = %s order by decided_at, action_id"),
            "audit": audit, "llm": llm, "seal": seal, "chain": await chain.verify_db(conn)}


def compose(facts: dict, *, people: dict[str, str], modes: dict[str, str], built_at: datetime) -> tuple[str, dict]:
    """(summary, body) from gathered facts. Pure: the same facts always give the same digest."""
    run, capsule = facts["run"], facts["run"]["capsule"] or {}
    view = build_view(run, facts["actions"], people=people, modes=modes)   # the same rows every door renders
    by_id = {a["id"]: a for a in facts["actions"]}
    stable = {
        "receipt_version": 1,
        "run": {k: run[k] for k in _RUN_FIELDS},
        "subject": capsule.get("subject"),
        "peer": capsule.get("peer"),
        "tally": view.counts,
        "actions": [{**row.model_dump(), "target": by_id[row.action_id]["target"],
                     "verified_at": by_id[row.action_id]["verified_at"],
                     "idempotency_key": by_id[row.action_id]["idempotency_key"]} for row in view.rows],
        "decisions": [{"action_id": d["action_id"], "approver": d["approver"],
                       "approver_name": people.get(d["approver"]), "decision": d["decision"], "reason": d["reason"],
                       "channel": d["channel"], "decided_at": d["decided_at"], "params_hash": d["params_hash"]}
                      for d in facts["approvals"]],
        "explanations": capsule.get("decisions", []),
        "evidence": [{k: e.get(k) for k in _EVIDENCE_FIELDS} for e in capsule.get("evidence", [])],
        "open_blockers": capsule.get("open_blockers", []),
        "capsule": facts["seal"],
        "audit": {k: facts["audit"][k] for k in ("from_seq", "to_seq", "events")},
        "connectors": dict(sorted(modes.items())),
        "llm": {"calls": facts["llm"]["calls"], "replay": facts["llm"]["replay"]},
    }
    stable = json.loads(canonical_json(stable))  # JSON-safe: UTC 'Z' datetimes, string UUIDs
    check = facts["chain"]
    body = {**stable, "digest": sha256_hex(stable), "built_at": built_at.astimezone(UTC).isoformat(),
            "chain": {"ok": check.ok, "rows": check.rows, "first_broken_seq": check.first_broken_seq,
                      "reason": check.reason}}
    return summarize(body), body


def _clip(text: str, n: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _capped(lines: list[str]) -> list[str]:
    return lines[:_SHOW] + ([f"  …and {len(lines) - _SHOW} more (full receipt JSON)"] if len(lines) > _SHOW else [])


def summarize(body: dict) -> str:
    run, t, acts = body["run"], body["tally"], body["actions"]
    lines = [f"ContextRail receipt · run {run['id'][:8]} · {run['status'].replace('_', ' ')}",
             f"Request ({run['source']}): \"{_clip(run['request_text'], 160)}\""]
    if body["subject"]:
        s, p = body["subject"], body["peer"]
        lines.append(f"Subject: {s['display_name']} ({s['source_id']})"
                     + (f", same as {p['display_name']} ({p['source_id']})" if p else ""))
    lines.append(f"{LAMP['ALLOW']} {t['allow']} allowed · {LAMP['HOLD']} {t['hold']} held · "
                 f"{LAMP['REFUSE']} {t['refuse']} refused · {t['verified']} verified · {t['failed']} failed")
    lines += _capped([f"Refused: {a['label']} under {a['rule_id']}: \"{_clip(a['clause'], 140)}\""
                      for a in acts if a["verdict"] == "REFUSE"])
    lines += _capped([f"Waiting: {a['label']} for {a['approver_name'] or a['approver_id']} ({a['rule_id']})"
                      for a in acts if a["state"] == "awaiting"])
    labels = {a["action_id"]: a["label"] for a in acts}
    lines += _capped([f"Decided: {labels.get(d['action_id'], d['action_id'])} {d['decision']} by "
                      f"{d['approver_name'] or d['approver']} via {d['channel']}" for d in body["decisions"]])
    lines += _capped([f"Failed: {a['label']} ({a['state']})" for a in acts if a["state"] in ("failed", "unknown")])
    if body["open_blockers"]:
        lines.append(f"Blocked: {_clip('; '.join(body['open_blockers']), 200)}")
    cap, audit, check = body["capsule"], body["audit"], body["chain"]
    seal = {True: "seal verified", False: "seal BROKEN", None: "no case file"}[cap["seal_verified"]]
    digest = f"{cap['digest'][:8]}…{cap['digest'][-4:]}" if cap["digest"] else "none"
    chain_text = "chain intact" if check["ok"] else f"chain BROKEN at seq {check['first_broken_seq']}"
    lines.append(f"Case digest {digest} ({seal}) · audit seq {audit['from_seq']}–{audit['to_seq']} ({chain_text})")
    lines.append("Connectors: " + ", ".join(f"{k} {v}" for k, v in body["connectors"].items()))
    if body["llm"]["replay"]:
        lines.append("Some model text in this run was replayed from a recording (T4).")
    lines.append(f"Receipt {body['digest'][:12]}")
    return "\n".join(lines)


async def build_receipt(db: Database, run_id: UUID, *, people: dict[str, str], modes: dict[str, str],
                        now: datetime | None = None, note: bool = False) -> Receipt:
    """Build, store and chain the run's receipt, or return the stored one if nothing changed. LookupError if no run.

    `note=True` (a notes connector exists) queues 'receipt.note' for a new receipt of a ticket-backed run, in the same
    transaction as the receipt, so a stored receipt and its pending note cannot disagree."""
    async with advisory_lock(db, f"receipt:{run_id}") as c:
        facts = await _facts(c, run_id)
        if facts is None:
            raise LookupError(f"no run {run_id}")
        summary, body = compose(facts, people=people, modes=modes, built_at=now or datetime.now(UTC))
        audit = body["audit"]
        stored = await (await c.execute("select summary, body from receipts where run_id = %s", (run_id,))).fetchone()
        if stored and stored["body"].get("digest") == body["digest"]:
            await index_receipt(c, run_id)
            return Receipt(run_id=run_id, digest=body["digest"], summary=stored["summary"], body=stored["body"],
                           audit_from=audit["from_seq"], audit_to=audit["to_seq"], created=False)
        # fs_note_id belongs to the receipt it carried: a new receipt has not been posted yet.
        await c.execute("""
            insert into receipts (run_id, summary, body, audit_from, audit_to) values (%s, %s, %s, %s, %s)
            on conflict (run_id) do update set summary = excluded.summary, body = excluded.body,
                audit_from = excluded.audit_from, audit_to = excluded.audit_to, fs_note_id = null""",
            (run_id, summary, Jsonb(body), audit["from_seq"], audit["to_seq"]))
        await chain.append(c, run_id=run_id, event="receipt.built", payload={
            "digest": body["digest"], "status": body["run"]["status"], "audit_from": audit["from_seq"],
            "audit_to": audit["to_seq"], "chain_ok": body["chain"]["ok"],
            "seal_verified": body["capsule"]["seal_verified"]})
        await index_receipt(c, run_id)
        run = body["run"]
        if note and run["source"] in TICKET_CHANNELS and run["source_ref"]:
            await repo.enqueue_job(c, "receipt.note", {"run_id": str(run_id), "digest": body["digest"]},
                                   dedupe_key=f"receipt.note:{run_id}:{body['digest']}")
    return Receipt(run_id=run_id, digest=body["digest"], summary=summary, body=body, audit_from=audit["from_seq"],
                   audit_to=audit["to_seq"], created=True)


class _ReceiptJob(BaseModel):
    model_config = ConfigDict(extra="ignore")

    run_id: UUID


@handler("receipt.build")
async def receipt_build(platform, payload: dict) -> None:
    """Enqueued by finalize once per distinct outcome (rail/finalize.request_receipt)."""
    try:
        job = _ReceiptJob.model_validate(payload)
    except ValidationError as e:
        raise PermanentJobError(f"bad receipt.build payload: {e.errors(include_url=False)}") from None
    try:
        r = await build_receipt(platform.db, job.run_id, people=platform.door.people, modes=platform.modes,
                                note=platform.notes is not None)
    except LookupError as e:
        raise PermanentJobError(str(e)) from None
    log.info("receipt_built" if r.created else "receipt_unchanged", run_id=str(job.run_id), digest=r.digest)


# --- the receipt on the ticket (T211) ---------------------------------------------------------------------------

class TicketNotes(Protocol):
    """Implemented by the Freshservice connector: POST /api/v2/tickets/{id}/notes as a private note (section I, T127).

    `body` is plain text; the connector turns it into the note's HTML (escaping, line breaks). Returns the note id.
    Labelled LIVE or FIXTURE like every connector (D-004); the mode is written to the audit chain with the note."""

    mode: str

    async def add_private_note(self, ticket_id: str, body: str) -> str: ...


class _NoteJob(BaseModel):
    model_config = ConfigDict(extra="ignore")

    run_id: UUID
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")


@handler("receipt.note")
async def receipt_note(platform, payload: dict) -> None:
    """Post the stored receipt's summary to its ticket, once per receipt.

    Skips a receipt that a newer one replaced (the newer one has its own job) or that already has a note. The note
    ends with the receipt's digest prefix, so a person, or a later reconcile, can match note to receipt. Known gap:
    if the note is created but recording its id fails, the retry posts a second note; closing it needs a read-back
    of the ticket's notes, which the protocol does not offer yet."""
    try:
        job = _NoteJob.model_validate(payload)
    except ValidationError as e:
        raise PermanentJobError(f"bad receipt.note payload: {e.errors(include_url=False)}") from None
    notes = platform.notes
    if notes is None:
        raise PermanentJobError("no Freshservice notes connector configured (Platform.notes)")
    async with advisory_lock(platform.db, f"receipt:{job.run_id}") as c:
        row = await (await c.execute("""
            select r.summary, r.body->>'digest' as digest, r.fs_note_id, runs.source_ref
            from receipts r join runs on runs.id = r.run_id where r.run_id = %s""", (job.run_id,))).fetchone()
        if row is None:
            raise PermanentJobError(f"no receipt for run {job.run_id}")
        if row["digest"] != job.digest or row["fs_note_id"]:
            log.info("receipt_note_skipped", run_id=str(job.run_id),
                     reason="superseded" if row["digest"] != job.digest else "already posted")
            return
        note_id = await notes.add_private_note(row["source_ref"], row["summary"])
        await c.execute("update receipts set fs_note_id = %s where run_id = %s", (note_id, job.run_id))
        await chain.append(c, run_id=job.run_id, event="receipt.noted", payload={
            "digest": job.digest, "ticket_id": row["source_ref"], "note_id": note_id, "mode": notes.mode})
    log.info("receipt_noted", run_id=str(job.run_id), ticket_id=row["source_ref"], mode=notes.mode)

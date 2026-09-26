"""The runner (CLAUDE.md §8, checklist T083): eight stages, fixed order, every stage audited and streamed.

The model never chooses the next stage: `check_stage_order` rejects any skip or reversal. Each stage commits its
own writes (actions, capsule, audit event, jobs) in one transaction, then emits a StageEvent. The capsule is sealed
after every stage and re-verified at handoff (P5). Allowed work proceeds while held work waits: a run with holds
ends the first pass in `awaiting_approval`, and `resume()` continues it (approve -> execute -> verify -> finalize)
when a door records a decision.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from uuid import UUID

from contextrail import repo
from contextrail.audit import chain
from contextrail.canonical import idempotency_key
from contextrail.capsule import DigestMismatch
from contextrail.db import Database
from contextrail.knowledge.okf import Bundle
from contextrail.logs import bind_run, get_logger
from contextrail.models import (
    ActionState,
    CaseFile,
    RunStatus,
    Stage,
    check_run_transition,
    check_stage_order,
)
from contextrail.policy.engine import PolicyEngine
from contextrail.policy.schema import Rule
from contextrail.rail import approve, execute, finalize, govern, plan
from contextrail.rail import compile as compile_
from contextrail.rail import discover as discover_
from contextrail.rail import verify as verify_
from contextrail.rail.events import EventBus
from contextrail.rail.store import load_case, save_case

log = get_logger("contextrail.rail")


@dataclass
class RailDeps:
    db: Database
    registry: object
    engine: PolicyEngine
    rules: list[Rule]
    extractor: discover_.IntentExtractor
    explainer: object
    events: EventBus = field(default_factory=EventBus)
    backoff: Callable[[int], float] = execute.default_backoff
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    knowledge: Bundle | None = None   # OKF bundle: policy text comes from curated pages (T177)


class Runner:
    def __init__(self, deps: RailDeps) -> None:
        self.d = deps

    # --- plumbing -------------------------------------------------------------------------------------------

    async def _audit(self, conn, run_id: UUID, event: str, payload: dict) -> None:
        await chain.append(conn, run_id=run_id, event=event, payload=payload)

    async def _status(self, conn, run_id: UUID, to: RunStatus) -> None:
        row = await repo.get_run(conn, run_id)
        if row["status"] != to:
            check_run_transition(row["status"], to)
            await repo.set_stage(conn, run_id, status=to)

    async def _emit(self, run_id: UUID, stage: Stage, status: RunStatus, message: str,
                    case: CaseFile | None = None) -> None:
        await self.d.events.emit(run_id, stage, status, message, counts=finalize.tally(case) if case else None)

    async def _sync_actions(self, conn, case: CaseFile) -> None:
        for a in case.actions:
            await repo.upsert_action(
                conn, case.run_id, id=a.id, kind=a.kind, target=a.target, params_hash=a.params_hash,
                verdict=a.verdict, rule_id=a.rule_id, clause=a.clause, approver=a.approver, state=a.state,
                idempotency_key=idempotency_key(case.run_id, a.id, a.params_hash))

    # --- first pass: discover -> finalize --------------------------------------------------------------------

    async def start(self, *, source: str, request_text: str, source_ref: str | None = None,
                    requested_by: str | None = None) -> UUID:
        async with self.d.db.transaction() as c:
            row = await repo.create_run(c, source=source, request_text=request_text, source_ref=source_ref,
                                        requested_by=requested_by)
            await self._audit(c, row["id"], "run.created", {"source": source, "source_ref": source_ref,
                                                             "requested_by": requested_by})
        return row["id"]

    async def run(self, run_id: UUID, *, subject_id: str | None = None, peer_id: str | None = None) -> RunStatus:
        bind_run(run_id=str(run_id))
        async with self.d.db.transaction() as c:
            row = await repo.get_run(c, run_id)
            if row["status"] == RunStatus.NEEDS_INPUT:
                # The requester answered the question (picked a candidate): record it, then run again from Discover.
                await self._audit(c, run_id, "run.input_received", {"subject_id": subject_id, "peer_id": peer_id})
                await self._status(c, run_id, RunStatus.RUNNING)
            elif row["status"] != RunStatus.RUNNING:
                raise ValueError(f"run {run_id} is {row['status']}; only new or needs_input runs can run")
        prev: Stage | None = None

        # DISCOVER: AI reads (mentions), code resolves (exact lookup), ambiguity asks.
        prev = check_stage_order(prev, Stage.DISCOVER)
        t0 = time.perf_counter()
        found = await discover_.discover(row["request_text"], self.d.extractor, self.d.registry.get("hris"),
                                         subject_id=subject_id, peer_id=peer_id)
        audit = {"intent": found.intent.intent, "extractor": found.intent.extractor,
                 "subject_id": found.subject.source_id if found.subject else None,
                 "peer_id": found.peer.source_id if found.peer else None,
                 "needs": [n.model_dump() for n in found.needs], "ms": _ms(t0)}
        async with self.d.db.transaction() as c:
            await repo.set_stage(c, run_id, stage=Stage.DISCOVER, intent=found.intent.intent,
                                 subject_id=audit["subject_id"])
            await self._audit(c, run_id, "stage.discover", audit)
            if found.status == "needs_input":
                await self._status(c, run_id, RunStatus.NEEDS_INPUT)
        if found.status == "needs_input":
            await self._emit(run_id, Stage.DISCOVER, RunStatus.NEEDS_INPUT, _needs_message(found))
            return RunStatus.NEEDS_INPUT
        if found.subject is None:  # a query: answered by door.answer_query from receipts, not by the rail
            async with self.d.db.transaction() as c:
                await self._audit(c, run_id, "run.query_routed", {"intent": found.intent.intent})
                await self._status(c, run_id, RunStatus.DONE)
            await self._emit(run_id, Stage.DISCOVER, RunStatus.DONE, "This is a question; answered from receipts.")
            return RunStatus.DONE
        await self._emit(run_id, Stage.DISCOVER, RunStatus.RUNNING,
                         f"Found {found.subject.display_name} ({found.subject.source_id})"
                         + (f"; peer {found.peer.display_name} ({found.peer.source_id})" if found.peer else ""))

        # COMPILE: records, holdings, catalogue, role, policy, untrusted messages -> one sealed case file.
        prev = check_stage_order(prev, Stage.COMPILE)
        t0 = time.perf_counter()
        inputs = await compile_.gather_inputs(found.subject_record, found.peer_record,
                                              entitlements=self.d.registry.get("entitlements"), rules=self.d.rules,
                                              knowledge=self.d.knowledge)
        messages = await compile_.retrieve_messages(
            self.d.registry.get("slack_corpus"), compile_.search_terms(found.subject, found.peer, found.intent.intent))
        evidence, blockers = compile_.mark_stale(inputs.evidence + messages)
        blockers = [*inputs.blockers, *blockers]
        case = CaseFile(run_id=run_id, request_text=row["request_text"], intent=found.intent.intent,
                        subject=found.subject, peer=found.peer, evidence=evidence,
                        constraints=compile_.subject_constraints(found.subject), open_blockers=blockers)
        async with self.d.db.transaction() as c:
            case = await save_case(c, case, stage=Stage.COMPILE)
            await self._audit(c, run_id, "stage.compile", {"evidence": len(evidence), "untrusted": len(messages),
                                                           "blockers": blockers, "digest": case.digest, "ms": _ms(t0)})
        await self._emit(run_id, Stage.COMPILE, RunStatus.RUNNING,
                         f"Case file sealed: {len(evidence)} pieces of evidence, {len(messages)} untrusted", case)

        # GOVERN: code over records. The engine is never handed evidence.
        prev = check_stage_order(prev, Stage.GOVERN)
        governed = govern.evaluate(
            govern.build_candidates(case.intent, case.request_text, case.subject, inputs, case.peer),
            case.subject, self.d.engine, role=inputs.role, requested_by=row["requested_by"])
        case = case.model_copy(update={"actions": [g.action for g in governed]})
        async with self.d.db.transaction() as c:
            case = await save_case(c, case, stage=Stage.GOVERN)
            await self._sync_actions(c, case)
            await self._audit(c, run_id, "stage.govern", {
                "verdicts": {g.action.id: [g.verdict.verdict, g.verdict.rule_id] for g in governed},
                "digest": case.digest})
        t = finalize.tally(case)
        await self._emit(run_id, Stage.GOVERN, RunStatus.RUNNING,
                         f"Govern: {t['allow']} allowed, {t['hold']} held, {t['refuse']} refused", case)

        # PLAN: order, transfer revocations, one-line explanations (text only).
        prev = check_stage_order(prev, Stage.PLAN)
        ordered = plan.build_plan(governed, case.subject, found.subject_record, inputs, self.d.engine,
                                  requested_by=row["requested_by"])
        case = case.model_copy(update={"actions": [g.action for g in ordered],
                                       "decisions": plan.explanations(ordered, self.d.explainer)})
        async with self.d.db.transaction() as c:
            case = await save_case(c, case, stage=Stage.PLAN)
            await self._sync_actions(c, case)
            await self._audit(c, run_id, "stage.plan", {"order": [a.id for a in case.actions],
                                                        "decisions": case.decisions, "digest": case.digest})
        await self._emit(run_id, Stage.PLAN, RunStatus.RUNNING, f"Plan: {len(case.actions)} steps, refusals kept", case)

        # HANDOFF: the next stages receive the case by value and re-verify its seal.
        prev = check_stage_order(prev, Stage.HANDOFF)
        case = await self._handoff(run_id)
        if case is None:
            return RunStatus.FAILED
        return await self._continue(run_id, case, prev)

    async def _handoff(self, run_id: UUID) -> CaseFile | None:
        try:
            async with self.d.db.connection() as c:
                case = await load_case(c, run_id)
        except DigestMismatch as e:
            async with self.d.db.transaction() as c:
                await self._audit(c, run_id, "capsule.digest_mismatch", {"expected": e.expected, "actual": e.actual})
                await self._status(c, run_id, RunStatus.FAILED)
            await self._emit(run_id, Stage.HANDOFF, RunStatus.FAILED, "Halted: the case file was altered")
            return None
        async with self.d.db.transaction() as c:
            await repo.set_stage(c, run_id, stage=Stage.HANDOFF)
            await self._audit(c, run_id, "stage.handoff", {"digest": case.digest, "verified": True})
        await self._emit(run_id, Stage.HANDOFF, RunStatus.RUNNING, "Handoff: case file seal verified", case)
        return case

    # --- approve -> execute -> verify -> finalize (first pass and every resume) ------------------------------

    async def _continue(self, run_id: UUID, case: CaseFile, prev: Stage) -> RunStatus:
        # APPROVE
        prev = check_stage_order(prev, Stage.APPROVE)
        async with self.d.db.transaction() as c:
            decided, void = await approve.apply_decisions(c, case)
            dispatched, unresolved = await approve.dispatch_holds(c, case)
            blockers = list(dict.fromkeys([*case.open_blockers, *unresolved]))
            case = await save_case(c, case.model_copy(update={"open_blockers": blockers}), stage=Stage.APPROVE)
            await self._sync_states(c, case, decided)
            await self._audit(c, run_id, "stage.approve", {"decided": decided, "void": void,
                                                           "dispatched": dispatched, "digest": case.digest})
        await self._emit(run_id, Stage.APPROVE, RunStatus.RUNNING,
                         f"Approve: {len(dispatched)} sent for approval, {len(decided)} decided", case)

        # EXECUTE: nothing executes while a blocker is open.
        prev = check_stage_order(prev, Stage.EXECUTE)
        executed = []
        if not case.open_blockers:
            for a in case.actions:
                if execute.is_executable(a):
                    out = await execute.execute_action(a, run_id=run_id, registry=self.d.registry,
                                                       backoff=self.d.backoff, sleep=self.d.sleep)
                    a.transition(out.state)
                    executed.append({"action_id": a.id, "state": out.state, "attempts": out.attempts,
                                     "replayed": out.replayed, "note": out.note})
        async with self.d.db.transaction() as c:
            case = await save_case(c, case, stage=Stage.EXECUTE)
            await self._sync_states(c, case, [e["action_id"] for e in executed])
            await self._audit(c, run_id, "stage.execute", {"results": executed, "skipped_for_blockers":
                                                           bool(case.open_blockers), "digest": case.digest})
        await self._emit(run_id, Stage.EXECUTE, RunStatus.RUNNING, f"Execute: {len(executed)} written", case)

        # VERIFY: read back; a 200 is not done.
        prev = check_stage_order(prev, Stage.VERIFY)
        checks, verified_at = [], {}
        for a in case.actions:
            if a.state in verify_.VERIFIABLE:
                out = await verify_.verify_action(a, registry=self.d.registry)
                a.transition(out.state)
                verified_at[a.id] = out.at
                checks.append({"action_id": a.id, "state": out.state, "observed": out.observed, "note": out.note})
        async with self.d.db.transaction() as c:
            case = await save_case(c, case, stage=Stage.VERIFY)
            await self._sync_states(c, case, [x["action_id"] for x in checks], verified_at)
            await self._audit(c, run_id, "stage.verify", {"checks": checks, "digest": case.digest})
        t = finalize.tally(case)
        await self._emit(run_id, Stage.VERIFY, RunStatus.RUNNING,
                         f"Verify: {t['verified']} verified, {t['failed']} failed", case)

        # FINALIZE
        check_stage_order(prev, Stage.FINALIZE)
        status = finalize.final_status(case)
        async with self.d.db.transaction() as c:
            case = await save_case(c, case, stage=Stage.FINALIZE)
            await self._status(c, run_id, status)
            await finalize.request_receipt(c, case, status)
            await self._audit(c, run_id, "stage.finalize", {"status": status, "tally": finalize.tally(case),
                                                            "digest": case.digest})
        t = finalize.tally(case)
        await self._emit(run_id, Stage.FINALIZE, status,
                         f"{status}: {t['verified']} verified, {t['hold']} held, {t['refuse']} refused", case)
        return status

    async def _sync_states(self, conn, case: CaseFile, ids: list[str], verified_at: dict | None = None) -> None:
        for aid in ids:
            a = case.action(aid)
            await repo.set_action_state(conn, case.run_id, aid, a.state,
                                        verified_at=(verified_at or {}).get(aid) if a.state is ActionState.VERIFIED
                                        else None)

    async def resume(self, run_id: UUID) -> RunStatus:
        """Continue a run after a decision: approve -> execute -> verify -> finalize, from a re-verified capsule."""
        bind_run(run_id=str(run_id))
        async with self.d.db.transaction() as c:
            row = await repo.get_run(c, run_id)
            if row["status"] != RunStatus.AWAITING_APPROVAL:
                return RunStatus(row["status"])
            await self._status(c, run_id, RunStatus.RUNNING)
            await self._audit(c, run_id, "run.resumed", {})
        case = await self._handoff(run_id)
        if case is None:
            return RunStatus.FAILED
        return await self._continue(run_id, case, Stage.HANDOFF)


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


def _needs_message(found: discover_.Discovery) -> str:
    n = found.needs[0]
    if n.reason == "ambiguous":
        names = ", ".join(f"{c.display_name} ({c.team})" for c in n.candidates)
        return f"Which {n.mention}? {names}"
    if n.reason == "unclear_request":
        return "What should be done, and for whom?"
    return f"Who is '{n.mention}'? No exact match was found." if n.mention else "Who is this request for?"

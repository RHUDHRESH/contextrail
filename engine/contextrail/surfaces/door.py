"""The door contract (checklist T107, CLAUDE.md §13.0). Slack, Email, Teams, Voice, the FDK sidebar and MCP may call
only these functions, and they render only RunView. Doors never decide (D-005).

decide() is the one place any door's approval lands, and it checks, in order:
1. the actor maps to a known person for that channel (identity_map);
2. the action exists and is still awaiting a decision;
3. the card was for exactly these parameters (params_hash), so a stale or forged card is rejected;
4. the actor is the named approver;
5. separation of duties (POL-SOD-001) via the policy engine: not the requester, not the beneficiary;
6. first decision wins across all doors (approvals PK); later ones learn who decided, where, and when.
Then it audits, queues the Freshservice mirror and cross-door card updates, and resumes the run.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from contextrail import repo
from contextrail.audit import chain
from contextrail.fixtures import subject_from_record
from contextrail.policy.engine import check_decision
from contextrail.rail.runner import Runner
from contextrail.surfaces.presenter import RunView, build_view

Channel = Literal["slack", "teams", "email", "voice", "freshservice", "mcp"]
_ID_COLUMN = {"slack": "slack_user_id", "teams": "teams_aad_id", "email": "email", "voice": "phone",
              "freshservice": "fs_agent_id", "mcp": "person_id"}


class DecisionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["recorded", "already_decided", "rejected"]
    reason: str | None = None
    rule_id: str | None = None
    decided_by: str | None = None
    decided_channel: str | None = None
    view: RunView | None = None


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    run_id: UUID | None = None
    citations: list[int] = []  # audit seq numbers the answer is drawn from


class Door:
    def __init__(self, runner: Runner, *, people: dict[str, str], modes: dict[str, str]) -> None:
        self.runner, self.db, self.engine = runner, runner.d.db, runner.d.engine
        self.people, self.modes = people, modes

    # --- identity -------------------------------------------------------------------------------------------

    async def resolve_actor(self, channel: Channel, external_id: str | None) -> dict | None:
        if not external_id:
            return None
        col = _ID_COLUMN[channel]
        sql = (f"select * from identity_map where lower({col}) = lower(%s)" if col == "email"
               else f"select * from identity_map where {col} = %s")
        async with self.db.connection() as c:
            return await (await c.execute(sql, (external_id,))).fetchone()

    # --- start / status / pick ------------------------------------------------------------------------------

    async def start_run(self, text: str, *, channel: Channel, actor_external_id: str | None,
                        source_ref: str | None = None) -> RunView:
        actor = await self.resolve_actor(channel, actor_external_id)
        rid = await self.runner.start(source=channel, request_text=text, source_ref=source_ref,
                                      requested_by=actor["person_id"] if actor else None)
        await self.runner.run(rid)
        return await self.get_status(rid)

    async def get_status(self, run_id: UUID) -> RunView:
        async with self.db.connection() as c:
            run = await repo.get_run(c, run_id)
            if run is None:
                raise LookupError(f"no run {run_id}")
            actions = await repo.list_actions(c, run_id)
            needs = []
            if run["status"] == "needs_input":
                row = await (await c.execute(
                    "select payload from audit where run_id = %s and event = 'stage.discover' order by seq desc "
                    "limit 1", (run_id,))).fetchone()
                needs = row["payload"]["needs"] if row else []
        return build_view(run, actions, people=self.people, modes=self.modes, needs=needs)

    async def pick_candidate(self, run_id: UUID, role: Literal["subject", "peer"], source_id: str) -> RunView:
        """The requester answered 'which one?'. The pick is still looked up exactly by the rail, never trusted blind."""
        await self.runner.run(run_id, **{f"{role}_id": source_id})
        return await self.get_status(run_id)

    # --- decide ---------------------------------------------------------------------------------------------

    async def decide(self, run_id: UUID, action_id: str, params_hash: str, *, channel: Channel,
                     actor_external_id: str | None, decision: Literal["approved", "refused"],
                     reason: str | None = None) -> DecisionResult:
        actor = await self.resolve_actor(channel, actor_external_id)
        if actor is None:
            return await self._reject(run_id, action_id, channel, actor_external_id, "unknown identity for this door")
        person = actor["person_id"]
        async with self.db.connection() as c:
            run = await repo.get_run(c, run_id)
            action = await (await c.execute("select * from actions where run_id = %s and id = %s",
                                            (run_id, action_id))).fetchone()
            existing = await repo.get_approval(c, run_id, action_id)
        if run is None or action is None:
            return await self._reject(run_id, action_id, channel, person, "no such action")
        if existing:
            return DecisionResult(outcome="already_decided", decided_by=existing["approver"],
                                  decided_channel=existing["channel"], reason=f"already {existing['decision']}")
        if action["state"] != "awaiting":
            return await self._reject(run_id, action_id, channel, person, f"action is {action['state']}, not awaiting")
        if action["params_hash"] != params_hash:
            return await self._reject(run_id, action_id, channel, person,
                                      "this card is out of date: the action's parameters changed")
        if action["approver"] != person:
            return await self._reject(run_id, action_id, channel, person,
                                      f"only {self.people.get(action['approver'], action['approver'])} can decide this")
        beneficiary = await self._beneficiary(run["subject_id"])
        sod = check_decision(self.engine, subject_from_record(await self._subject_record(run["subject_id"])),
                             action_id=action_id, params_hash=params_hash, approver=person,
                             requested_by=run["requested_by"], beneficiary=beneficiary)
        if sod.verdict != "ALLOW":
            return await self._reject(run_id, action_id, channel, person, sod.clause_text, rule_id=sod.rule_id)

        async with self.db.transaction() as c:
            won = await repo.record_approval(c, run_id, action_id, params_hash=params_hash, approver=person,
                                             decision=decision, channel=channel, reason=reason)
            if won:
                await chain.append(c, run_id=run_id, event="approval.decided",
                                   payload={"action_id": action_id, "approver": person, "decision": decision,
                                            "channel": channel, "reason": reason, "params_hash": params_hash})
                await repo.enqueue_job(c, "fs.approval.mirror", {"run_id": str(run_id), "action_id": action_id},
                                       dedupe_key=f"fs.approval.mirror:{run_id}:{action_id}")
                await repo.enqueue_job(c, "door.update", {"run_id": str(run_id), "action_id": action_id,
                                                          "decided_by": person, "channel": channel},
                                       dedupe_key=f"door.update:{run_id}:{action_id}")
        if not won:  # another door got there between our read and our write
            async with self.db.connection() as c:
                first = await repo.get_approval(c, run_id, action_id)
            return DecisionResult(outcome="already_decided", decided_by=first["approver"],
                                  decided_channel=first["channel"], reason=f"already {first['decision']}")
        await self.runner.resume(run_id)
        return DecisionResult(outcome="recorded", decided_by=person, decided_channel=channel,
                              view=await self.get_status(run_id))

    async def _reject(self, run_id, action_id, channel, who, reason, rule_id=None) -> DecisionResult:
        async with self.db.transaction() as c:
            if await repo.get_run(c, run_id):
                await chain.append(c, run_id=run_id, event="approval.rejected",
                                   payload={"action_id": action_id, "channel": channel, "actor": who,
                                            "reason": reason, "rule_id": rule_id})
        return DecisionResult(outcome="rejected", reason=reason, rule_id=rule_id)

    async def _beneficiary(self, subject_id: str | None) -> str | None:
        async with self.db.connection() as c:
            row = await (await c.execute("select person_id from identity_map where hris_id = %s",
                                         (subject_id,))).fetchone()
        return row["person_id"] if row else subject_id

    async def _subject_record(self, subject_id: str) -> dict:
        return await self.runner.d.registry.get("hris").read({"source_id": subject_id})

    # --- questions: answered from stored, verified facts only -------------------------------------------------

    async def answer_query(self, question: str, *, channel: Channel, actor_external_id: str | None) -> Answer:
        """Answers 'what happened to my request?' from the run's audit and action states, citing audit seq numbers.
        No model writes these facts. (Receipt-based answers with the audit_answer prompt arrive with T121/T210.)"""
        actor = await self.resolve_actor(channel, actor_external_id)
        async with self.db.connection() as c:
            run = await (await c.execute(
                "select * from runs where requested_by = %s and intent <> 'query' order by created_at desc limit 1",
                (actor["person_id"] if actor else None,))).fetchone()
            if run is None:
                return Answer(text="I can't find a request from you yet.")
            seqs = [r["seq"] for r in await (await c.execute(
                "select seq from audit where run_id = %s and event in ('stage.finalize', 'approval.decided') "
                "order by seq", (run["id"],))).fetchall()]
        v = await self.get_status(run["id"])
        waiting = [r.approver_name or r.approver_id for r in v.rows if r.state == "awaiting"]
        refused = [f"{r.label} ({r.rule_id})" for r in v.rows if r.verdict == "REFUSE"]
        status = v.status.replace("_", " ")
        parts = [f"Your request \"{v.request_text}\" is {status}: {v.counts['verified']} done and verified"]
        if waiting:
            parts.append(f"{len(waiting)} waiting for {', '.join(waiting)}")
        if refused:
            parts.append(f"{len(refused)} refused: {'; '.join(refused)}")
        return Answer(text=", ".join(parts) + ".", run_id=run["id"], citations=seqs)

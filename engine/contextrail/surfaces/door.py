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

import re
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from contextrail import repo
from contextrail.audit import chain
from contextrail.fixtures import subject_from_record
from contextrail.memory import ConversationMemory
from contextrail.policy.engine import check_decision
from contextrail.rail.runner import Runner
from contextrail.surfaces.presenter import RunView, build_view

if TYPE_CHECKING:
    from contextrail.llm.question_agent import ReadOnlyQuestionAgent
    from contextrail.surfaces.read_tools import PlatformReadTools

Channel = Literal["slack", "teams", "email", "voice", "freshservice", "mcp"]
_ID_COLUMN = {"slack": "slack_user_id", "teams": "teams_aad_id", "email": "email", "voice": "phone",
              "freshservice": "fs_requester_id", "mcp": "person_id"}
_NAMED_STATUS = re.compile(r"\b(?:status|update)\s+(?:on|of|for)\s+(.+?)\s*[?.!]*$", re.IGNORECASE)
_TICKET_REFERENCE = re.compile(r"^(?:(?:my\s+)?(?:ticket|request)\s*)?#(\d+)$|^(?:my\s+)?(?:ticket|request)\s+(\d+)$",
                               re.IGNORECASE)
_SHORT_RUN = re.compile(r"^run\s+(.+)$", re.IGNORECASE)
_SPOKEN_DIGITS = {"zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4",
                  "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9"}


def _short_run_prefix(reference: str) -> str | None:
    """The voice door speaks the first eight UUID hex characters separately; accept that exact spelling."""
    match = _SHORT_RUN.fullmatch(reference)
    if match is None:
        return None
    tokens = re.split(r"[\s,.-]+", match.group(1).strip().lower())
    if len(tokens) == 1 and re.fullmatch(r"[0-9a-f]{8}", tokens[0]):
        return tokens[0]
    normalized = "".join(_SPOKEN_DIGITS.get(token, token) for token in tokens)
    return normalized if len(tokens) == 8 and re.fullmatch(r"[0-9a-f]{8}", normalized) else None


def _named_reference(question: str) -> str | None:
    """Extract an explicit 'status/update on X'; pronouns still mean this thread or the latest run."""
    match = _NAMED_STATUS.search(question.strip())
    if not match:
        return None
    reference = match.group(1).strip().strip("\"' ")
    if not reference:
        return None
    if not _TICKET_REFERENCE.fullmatch(reference) and reference.casefold().startswith(
            ("my ", "this ", "that ", "the request")):
        return None
    return reference


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
    sources: list[str] = []      # knowledge chunk IDs or audit references for grounded answers


class Door:
    def __init__(self, runner: Runner, *, people: dict[str, str], modes: dict[str, str]) -> None:
        self.runner, self.db, self.engine = runner, runner.d.db, runner.d.engine
        self.people, self.modes = people, modes
        self.memory = ConversationMemory(self.db)
        self.read_tools: PlatformReadTools | None = None
        self.question_agent: ReadOnlyQuestionAgent | None = None

    # --- identity -------------------------------------------------------------------------------------------

    async def resolve_actor(self, channel: Channel, external_id: str | None, *, for_approval: bool = False) -> dict | None:
        if not external_id:
            return None
        # Ticket intake presents a requester ID or the verified requester email. Freshservice approval callbacks
        # present an agent ID. The two numeric ID namespaces are never searched together.
        col = ("fs_agent_id" if for_approval else ("email" if "@" in external_id else "fs_requester_id")) \
            if channel == "freshservice" else _ID_COLUMN[channel]
        sql = (f"select * from identity_map where lower({col}) = lower(%s)" if col == "email"
               else f"select * from identity_map where {col} = %s")
        async with self.db.connection() as c:
            return await (await c.execute(sql, (external_id,))).fetchone()

    # --- start / status / pick ------------------------------------------------------------------------------

    async def start_run(self, text: str, *, channel: Channel, actor_external_id: str | None,
                        source_ref: str | None = None, subject_id: str | None = None,
                        peer_id: str | None = None) -> RunView:
        """subject_id / peer_id pin a system-of-record ID the caller already holds; the rail still looks it up."""
        actor = await self.resolve_actor(channel, actor_external_id)
        rid = await self.runner.start(source=channel, request_text=text, source_ref=source_ref,
                                      requested_by=actor["person_id"] if actor else None)
        await self.runner.run(rid, subject_id=subject_id, peer_id=peer_id)
        if actor:
            await self.memory.append(channel=channel, person_id=actor["person_id"],
                                     thread_ref=source_ref or str(rid), role="user", summary="Request recorded",
                                     run_id=rid)
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
        actor = await self.resolve_actor(channel, actor_external_id, for_approval=True)
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

    async def answer_query(self, question: str, *, channel: Channel, actor_external_id: str | None,
                           thread_ref: str | None = None) -> Answer:
        """Answer personal status from the audit, or a general policy question from cited indexed knowledge."""
        actor = await self.resolve_actor(channel, actor_external_id)
        status_question = bool(re.search(r"\b(?:status|update|my request|what happened|why|refus(?:e|ed|al)|denied)\b",
                                         question, re.IGNORECASE))
        if not status_question and self.read_tools is not None:
            person_id = actor["person_id"] if actor else None
            if self.question_agent is not None:
                grounded = await self.question_agent.ask(question, actor_id=person_id)
                if not grounded.citations:
                    found = await self.read_tools.search_knowledge(question, actor_id=person_id)
                    if found.supported:
                        from contextrail.llm.question_agent import QuestionAnswer

                        grounded = QuestionAnswer(text=found.text, citations=found.citations,
                                                  tools_used=[*grounded.tools_used, "search_knowledge"],
                                                  author="knowledge")
            else:
                from contextrail.llm.question_agent import QuestionAnswer

                found = await self.read_tools.search_knowledge(question, actor_id=person_id)
                grounded = QuestionAnswer(text=found.text, citations=found.citations,
                                          tools_used=["search_knowledge"],
                                          author="knowledge" if found.supported else "none")
            audit = [int(source.removeprefix("audit:")) for source in grounded.citations
                     if source.startswith("audit:") and source.removeprefix("audit:").isdigit()]
            return Answer(text=grounded.text, citations=audit, sources=grounded.citations)
        if actor is None:
            return Answer(text="I can't find a request from you yet.")
        # Memory supplies only a cited run pointer. The run and ownership are checked again below.
        remembered = (await self.memory.recent(channel=channel, person_id=actor["person_id"],
                                               thread_ref=thread_ref) if thread_ref else [])
        reference = _named_reference(question)
        async with self.db.connection() as c:
            run = None
            if reference:
                ticket = _TICKET_REFERENCE.fullmatch(reference)
                ref = (ticket.group(1) or ticket.group(2)) if ticket else reference
                if ref.isdecimal():
                    ticket = ticket or _TICKET_REFERENCE.fullmatch(f"ticket {ref}")
                short_run = _short_run_prefix(ref)
                try:
                    run_id = UUID(re.sub(r"^run\s+", "", ref, flags=re.IGNORECASE))
                except ValueError:
                    run_id = None
                if run_id is not None:
                    run = await (await c.execute(
                        "select * from runs where id = %s and requested_by = %s and intent <> 'query'",
                        (run_id, actor["person_id"]))).fetchone()
                elif short_run:
                    matches = await (await c.execute(
                        """select * from runs where requested_by = %s and id::text like %s
                           and intent <> 'query' order by created_at desc limit 2""",
                        (actor["person_id"], short_run + "%"))).fetchall()
                    if len(matches) > 1:
                        return Answer(text="I found multiple requests for that reference. Please use the full run ID.")
                    run = matches[0] if len(matches) == 1 else None
                elif ticket:
                    matches = await (await c.execute(
                        """select r.* from runs r where r.requested_by = %s and r.intent <> 'query'
                           and ((r.source in ('freshservice','email') and r.source_ref = %s)
                                or exists (select 1 from door_messages d where d.run_id = r.id
                                           and d.channel = 'freshservice' and d.ref->>'ticket_id' = %s))
                           order by r.created_at desc limit 2""",
                        (actor["person_id"], ref, ref))).fetchall()
                    if len(matches) > 1:
                        return Answer(text="I found multiple requests for that reference. Please use the full run ID.")
                    run = matches[0] if matches else None
                else:
                    matches = await (await c.execute(
                        """select * from runs where requested_by = %s and intent <> 'query'
                           and (source_ref = %s or lower(capsule->'subject'->>'display_name') = lower(%s)
                                or subject_id = %s)
                           order by created_at desc limit 2""",
                        (actor["person_id"], ref, ref, ref))).fetchall()
                    if len(matches) > 1:
                        return Answer(text="I found multiple requests for that reference. Please use a ticket or run ID.")
                    run = matches[0] if matches else None
                if run is None:
                    return Answer(text="I can't find a request from you for that reference.")
            if run is None and thread_ref:
                run = await (await c.execute(
                    "select * from runs where requested_by = %s and source_ref = %s and intent <> 'query' "
                    "order by created_at desc limit 1", (actor["person_id"], thread_ref))).fetchone()
            if run is None and remembered:
                run = await (await c.execute(
                    "select * from runs where id = %s and requested_by = %s and intent <> 'query'",
                    (remembered[-1].run_id, actor["person_id"]))).fetchone()
            run = await (await c.execute(
                "select * from runs where requested_by = %s and intent <> 'query' order by created_at desc limit 1",
                (actor["person_id"],))).fetchone() if run is None else run
            if run is None:
                return Answer(text="I can't find a request from you yet.")
            explain_refusal = bool(re.search(r"\b(?:why|reason|refus(?:e|ed|al)|denied)\b", question, re.IGNORECASE))
            events = ("stage.finalize", "approval.decided", "stage.govern") if explain_refusal else (
                "stage.finalize", "approval.decided")
            seqs = [r["seq"] for r in await (await c.execute(
                "select seq from audit where run_id = %s and event = any(%s) order by seq",
                (run["id"], list(events)))).fetchall()]
        v = await self.get_status(run["id"])
        waiting = [r.approver_name or r.approver_id for r in v.rows if r.state == "awaiting"]
        refused = [f"{r.label} ({r.rule_id})" for r in v.rows if r.verdict == "REFUSE"]
        status = v.status.replace("_", " ")
        parts = [f"Your request \"{v.request_text}\" is {status}: {v.counts['verified']} done and verified"]
        if waiting:
            parts.append(f"{len(waiting)} waiting for {', '.join(waiting)}")
        if refused:
            parts.append(f"{len(refused)} refused: {'; '.join(refused)}")
            if explain_refusal:
                clauses = [f"{r.label}: {r.clause} ({r.rule_id})" for r in v.rows if r.verdict == "REFUSE"]
                parts.append("Recorded reasons: " + "; ".join(clauses))
        answer = Answer(text=", ".join(parts) + ".", run_id=run["id"], citations=seqs,
                        sources=[f"audit:{seq}" for seq in seqs])
        # Fixed summaries preserve the pointer and audit citation without retaining PII from the question/answer.
        if thread_ref:
            await self.memory.append(channel=channel, person_id=actor["person_id"], thread_ref=thread_ref,
                                     role="user", summary="Status question", run_id=run["id"])
            await self.memory.append(channel=channel, person_id=actor["person_id"], thread_ref=thread_ref,
                                     role="assistant", summary=f"Status {v.status}; verified {v.counts['verified']}",
                                     run_id=run["id"], audit_seqs=tuple(seqs))
        return answer

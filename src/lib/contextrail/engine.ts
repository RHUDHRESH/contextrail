import { AGENTS } from "./agents";
import { compileCapsule, newDecision } from "./capsule";
import { executeAction } from "./executor";
import { generateActionPlan } from "./planner";
import { INTENTS } from "./intent";
import { saveRun, getRun } from "./store";
import type { Approval, ContextCapsule, Decision, RailEvent, Run } from "./types";

/* ------------------------------------------------------------------ *
 * The orchestration graph. Phase one assembles and governs; it stops
 * at the approval gate. Phase two executes what was approved and
 * verifies each outcome. Both phases emit the same event stream, so
 * the interface renders one continuous rail.
 * ------------------------------------------------------------------ */

const tick = (ms: number) => new Promise((r) => setTimeout(r, ms));

export type AssembleInput = {
  request: string;
  requesterId?: string;
  tenantId?: string;
  scenarioId?: string | null;
  /** Set to 0 in tests; the UI uses the default to make the rail readable. */
  pace?: number;
};

export async function* assemble(input: AssembleInput): AsyncGenerator<RailEvent> {
  const pace = input.pace ?? 220;
  const audit: Decision[] = [];
  const emitAudit = (d: Decision): RailEvent => {
    audit.push(d);
    return { type: "audit", decision: d };
  };

  try {
    /* ------------------------------ discover ------------------------------ */
    yield { type: "stage", stage: "discover", status: "running", note: "Sweeping connected knowledge sources" };
    await tick(pace);

    const compiled = compileCapsule({
      request: input.request,
      requesterId: input.requesterId,
      tenantId: input.tenantId,
    });
    const intentDef = INTENTS.find((i) => i.id === compiled.intentId)!;

    for (const e of compiled.evidence) {
      yield { type: "evidence", evidence: e };
      await tick(Math.max(40, pace / 3));
    }

    const systems = [...new Set(compiled.evidence.map((e) => e.system))];
    yield {
      type: "stage",
      stage: "discover",
      status: "done",
      note: `${compiled.evidence.length} pieces of evidence from ${systems.length} systems`,
    };
    yield emitAudit(
      newDecision("intent_resolved", "DISCOVERY", `Searched ${intentDef.sources.length} connected systems, kept ${compiled.evidence.length} sources above the confidence floor`, {
        systems,
      }),
    );

    /* ------------------------------ compile ------------------------------- */
    yield { type: "stage", stage: "compile", status: "running", note: "Building the Context Capsule" };
    await tick(pace);
    yield { type: "capsule", capsule: compiled.capsule };
    yield {
      type: "stage",
      stage: "compile",
      status: "done",
      note: `Capsule ${compiled.capsule.request_id} — intent "${intentDef.label}" at ${(compiled.capsule.intent_confidence * 100).toFixed(0)}%`,
    };

    /* ------------------------------- govern ------------------------------- */
    yield { type: "stage", stage: "govern", status: "running", note: "Evaluating policies and permissions" };
    await tick(pace);
    for (const d of compiled.governance.decisions) {
      yield { type: "policy", decision: d };
      await tick(Math.max(50, pace / 2.5));
    }
    const denies = compiled.governance.decisions.filter((d) => d.effect === "deny").length;
    yield {
      type: "stage",
      stage: "govern",
      status: denies > 0 ? "blocked" : "done",
      note: `${compiled.governance.decisions.length} policies applied — ${denies} action(s) forbidden outright`,
    };
    yield emitAudit(
      newDecision("policy_evaluated", "GOVERNANCE", `Applied ${compiled.governance.decisions.length} policies from families: ${intentDef.policyFamilies.join(", ")}`, {
        decisions: compiled.governance.decisions.map((d) => ({ id: d.policyId, effect: d.effect })),
      }),
    );

    /* -------------------------------- plan -------------------------------- */
    yield { type: "stage", stage: "plan", status: "running", note: "Generating the action plan" };
    await tick(pace);
    const plan = generateActionPlan(compiled.capsule, compiled.facts, compiled.governance, intentDef.entryAgent);
    compiled.capsule.planned_actions = plan.actions.filter((a) => !a.blockedBy).map((a) => a.title);
    yield { type: "plan", plan };
    yield { type: "stage", stage: "plan", status: "done", note: plan.summary };
    yield emitAudit(newDecision("plan_generated", "PLANNER", plan.summary, { plan_id: plan.plan_id }));

    /* ------------------------------ handoff ------------------------------- */
    yield { type: "stage", stage: "handoff", status: "running", note: "Routing subtasks to specialist agents" };
    await tick(pace);

    const chain: Run["capsule"]["handoff_chain"] = [];
    let from: "ORCHESTRATOR" | (typeof plan.agents)[number] = "ORCHESTRATOR";
    for (const agent of plan.agents) {
      const owned = plan.actions.filter((a) => a.agent === agent && !a.blockedBy);
      const carries = [
        `${compiled.capsule.sources.length} evidence items`,
        `${compiled.capsule.constraints.length} active constraints`,
        `${compiled.capsule.decisions.length + audit.length} prior decisions`,
        `${owned.length} assigned action(s)`,
        ...(compiled.capsule.open_blockers.length ? [`${compiled.capsule.open_blockers.length} open blocker(s)`] : []),
      ];
      yield { type: "handoff", from, to: agent, carries };
      yield emitAudit(
        newDecision("handoff", from, `Capsule handed to ${AGENTS[agent].name} carrying ${owned.length} action(s)`, { carries }),
      );
      chain.push(agent);
      from = agent;
      await tick(Math.max(90, pace / 2));
    }
    compiled.capsule.handoff_chain = chain;
    compiled.capsule.handoff_target = chain[chain.length - 1] ?? intentDef.entryAgent;
    yield {
      type: "stage",
      stage: "handoff",
      status: "done",
      note: `${chain.length} agent(s) hold the capsule — no context re-derived`,
    };

    /* ------------------------------- approve ------------------------------ */
    const approvals: Approval[] = plan.actions
      .filter((a) => a.approvalRequired && !a.blockedBy)
      .map((a, i) => ({
        id: `APR-${String(i + 1).padStart(2, "0")}`,
        actionId: a.id,
        title: a.title,
        approver: a.approver ?? "Approver",
        risk: a.risk,
        policyId: compiled.governance.gated.get(a.idempotencyKey.split(":")[1])?.policyId ?? "POLICY",
        why: a.rationale,
        state: "pending",
        decidedAt: null,
        note: null,
      }));

    if (approvals.length) {
      yield { type: "stage", stage: "approve", status: "running", note: `${approvals.length} privileged action(s) held for a human` };
      for (const a of approvals) {
        yield { type: "approval", approval: a };
        await tick(Math.max(60, pace / 3));
      }
    } else {
      yield { type: "stage", stage: "approve", status: "done", note: "No privileged actions in this plan" };
    }

    // A plan whose every action was refused has nothing left to run —
    // it is already settled, and should not sit in the queue as if work
    // were pending.
    const executable = plan.actions.filter((a) => !a.blockedBy);
    const settledOnRefusal = executable.length === 0;

    compiled.capsule.approval_required = approvals.length > 0;
    compiled.capsule.audit_status = settledOnRefusal ? "partial" : approvals.length ? "in_review" : "executing";
    yield { type: "capsule", capsule: compiled.capsule };

    const run: Run = {
      id: compiled.capsule.request_id,
      tenant_id: compiled.capsule.tenant_id,
      createdAt: compiled.capsule.created_at,
      request: input.request,
      requesterId: compiled.capsule.requester.id,
      scenarioId: input.scenarioId ?? null,
      capsule: compiled.capsule,
      policies: compiled.governance.decisions,
      plan,
      approvals,
      executions: [],
      audit: [...compiled.capsule.decisions, ...audit],
      status: settledOnRefusal ? "partial" : approvals.length ? "awaiting_approval" : "executing",
      metrics: {
        sources_touched: systems.length,
        evidence_count: compiled.evidence.length,
        actions_total: plan.actions.length,
        actions_completed: 0,
        actions_blocked: plan.actions.filter((a) => a.blockedBy).length,
        handoffs: chain.length,
        minutes_saved: plan.estimated_minutes_saved,
        policy_violations_prevented: plan.actions.filter((a) => a.blockedBy).length,
      },
    };

    saveRun(run);
    yield { type: "run", run };
  } catch (e) {
    yield { type: "error", message: e instanceof Error ? e.message : String(e) };
  }
}

export async function* executeRun(runId: string, pace = 320): AsyncGenerator<RailEvent> {
  const run = getRun(runId);
  if (!run) {
    yield { type: "error", message: `Run ${runId} not found` };
    return;
  }

  yield { type: "stage", stage: "execute", status: "running", note: "Running approved actions through MCP tools" };

  const executions = [];
  // The GitHub grant is the demo's designated flaky call — it fails once
  // and succeeds on retry, which is what the timeline is there to show.
  const flaky = run.plan.actions.find((a) => a.tool === "github.request_access")?.id;

  for (const action of run.plan.actions) {
    await tick(pace);
    const record = await executeAction(action, run.approvals, { flakyActionId: flaky });
    executions.push(record);
    yield { type: "execution", record };
    // Recorded, not merely streamed: a decision the UI saw but the run
    // never stored is not an audit trail. The hard-gate entry for a
    // refused action lives here.
    const execDecision = newDecision(
      record.status === "blocked" ? "action_blocked" : "action_executed",
      action.agent,
      `${action.title} → ${record.status}${record.attempts > 1 ? ` after ${record.attempts} attempts` : ""}`,
      { tool: action.tool, idempotencyKey: action.idempotencyKey },
    );
    run.audit.push(execDecision);
    yield { type: "audit", decision: execDecision };
  }

  yield { type: "stage", stage: "execute", status: "done", note: `${executions.filter((e) => e.status === "succeeded").length} action(s) executed` };

  /* ------------------------------- verify -------------------------------- */
  yield { type: "stage", stage: "verify", status: "running", note: "Probing each outcome" };
  await tick(pace);
  const verified = executions.filter((e) => e.verified).length;
  for (const e of executions.filter((x) => x.verified)) {
    const vd = newDecision("verification", e.agent, e.verification_note, { actionId: e.actionId });
    run.audit.push(vd);
    yield { type: "audit", decision: vd };
    await tick(Math.max(60, pace / 4));
  }

  const completed = executions.filter((e) => e.status === "succeeded").length;
  const blocked = executions.filter((e) => e.status === "blocked" || e.status === "skipped").length;

  run.executions = executions;
  run.metrics.actions_completed = completed;
  run.metrics.actions_blocked = blocked;
  run.capsule.audit_status = blocked > 0 ? "partial" : "complete";
  run.status = executions.some((e) => e.status === "failed") ? "failed" : blocked > 0 ? "partial" : "complete";
  run.audit.push(
    newDecision("verification", "ORCHESTRATOR", `${verified}/${completed} completed actions verified against their post-conditions`),
  );
  saveRun(run);

  yield { type: "stage", stage: "verify", status: blocked > 0 ? "blocked" : "done", note: `${verified} outcome(s) verified, ${blocked} not executed` };
  yield { type: "run", run };
}

export function capsuleForHandoff(capsule: ContextCapsule) {
  return {
    request_id: capsule.request_id,
    intent: capsule.intent,
    subject: capsule.subject,
    evidence: capsule.sources.map((s) => ({ system: s.system, title: s.title, confidence: s.confidence })),
    constraints: capsule.constraints.map((c) => c.statement),
    decisions_so_far: capsule.decisions.length,
    open_blockers: capsule.open_blockers,
    // Travels with the hop so the receiving agent can prove nothing was
    // dropped rather than take the sender's word for it.
    capsule_digest: capsule.capsule_digest,
  };
}

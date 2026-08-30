import { createHash } from "node:crypto";

import { TENANT } from "./data/corpus";
import { extractFacts, type Facts } from "./facts";
import { resolveIntent } from "./intent";
import { fetchAnchor, searchCorpus } from "./retrieval";
import { evaluatePolicies, type GovernanceResult } from "./policy";
import type { ContextCapsule, Decision, Evidence } from "./types";

/* ------------------------------------------------------------------ *
 * The Context Capsule: one portable, evidence-backed package that
 * travels with a request across every agent that touches it.
 * ------------------------------------------------------------------ */

export const REQUESTERS: Record<string, { id: string; name: string; role: string; department: string }> = {
  "U-2201": { id: "U-2201", name: "Marc Liu", role: "Engineering Manager", department: "Engineering" },
  "U-3310": { id: "U-3310", name: "Alicia Fenn", role: "Customer Success Manager", department: "Customer Success" },
  "U-1120": { id: "U-1120", name: "Priyanka Rao", role: "IT Provisioning Lead", department: "IT" },
};

let seq = 24_080;
export function nextRequestId(): string {
  seq += 1;
  return `REQ-${seq}`;
}

export function newDecision(kind: Decision["kind"], actor: string, summary: string, detail?: Record<string, unknown>): Decision {
  return {
    id: `dec_${Math.random().toString(36).slice(2, 9)}`,
    at: new Date().toISOString(),
    actor,
    kind,
    summary,
    detail,
  };
}

export type CompiledContext = {
  capsule: ContextCapsule;
  facts: Facts;
  governance: GovernanceResult;
  evidence: Evidence[];
  intentId: string;
};

export type CompileInput = {
  request: string;
  requesterId?: string;
  tenantId?: string;
  requestId?: string;
  /** Simulation only: evaluate as though these policies were not in force. */
  disabledPolicies?: ReadonlySet<string>;
};

export function compileCapsule(input: CompileInput): CompiledContext {
  const requester = REQUESTERS[input.requesterId ?? "U-2201"] ?? REQUESTERS["U-2201"];
  const match = resolveIntent(input.request);
  const intent = match.intent;

  const found = searchCorpus(input.request, {
    sources: intent.sources,
    boostTerms: Object.keys(intent.signals),
    limit: 9,
  });

  // Anchor records are fetched by identity, not discovered by search, so the
  // governing facts are the same whether the requester named the subject or not.
  const seen = new Set(found.map((e) => e.id));
  const pinned = intent.anchors
    .filter((id) => !seen.has(id))
    .map((id) => fetchAnchor(id))
    .filter((e): e is NonNullable<typeof e> => Boolean(e));

  const evidence = [...found, ...pinned].sort((a, b) => b.confidence - a.confidence);

  const facts = extractFacts(evidence, input.request);
  const governance = evaluatePolicies(facts, intent.id, intent.policyFamilies, evidence, input.disabledPolicies);

  const subject = buildSubject(intent.subjectKind, facts);

  const decisions: Decision[] = [
    newDecision(
      "intent_resolved",
      "ORCHESTRATOR",
      `Resolved intent "${intent.label}" at ${(match.confidence * 100).toFixed(0)}% confidence`,
      { matchedSignals: match.matchedSignals, runnerUp: match.runnerUp },
    ),
    newDecision(
      "policy_evaluated",
      "GOVERNANCE",
      `${governance.decisions.length} policies evaluated — ${governance.decisions.filter((d) => d.effect === "deny").length} deny, ${governance.decisions.filter((d) => d.effect === "require_approval").length} gated`,
      { policyIds: governance.decisions.map((d) => d.policyId) },
    ),
  ];

  const openBlockers = [
    ...governance.decisions.filter((d) => d.effect === "deny").map((d) => `${d.policyId}: ${d.title}`),
    ...evidence.filter((e) => e.stale).map((e) => `Stale source: ${e.title} (last verified ${e.lastVerifiedAt})`),
  ];

  const capsule: ContextCapsule = {
    request_id: input.requestId ?? nextRequestId(),
    tenant_id: input.tenantId ?? TENANT.id,
    created_at: new Date().toISOString(),
    intent: intent.id,
    intent_confidence: match.confidence,
    requester,
    subject,
    raw_request: input.request,
    sources: evidence,
    constraints: governance.constraints.map((c, i) => ({
      id: `CON-${String(i + 1).padStart(2, "0")}`,
      statement: c.statement,
      policyId: c.policyId,
      sourceEvidenceId: c.sourceEvidenceId,
      severity: c.severity,
    })),
    planned_actions: [],
    decisions,
    handoff_target: intent.entryAgent,
    handoff_chain: [intent.entryAgent],
    approval_required: governance.gated.size > 0,
    audit_status: "pending",
    open_blockers: openBlockers,
  };

  capsule.capsule_digest = capsuleDigest(capsule);

  return { capsule, facts, governance, evidence, intentId: intent.id };
}

/* ------------------------------------------------------------------ *
 * Capsule integrity.
 *
 * "Nobody summarises the deny out of existence" is the product claim.
 * A digest over the governance-bearing fields turns it into something a
 * receiving agent can check rather than trust. Evidence and prose are
 * deliberately excluded: an agent is allowed to add findings, but it is
 * not allowed to quietly drop a constraint, a decision, or a blocker.
 * ------------------------------------------------------------------ */

export function capsuleDigest(capsule: ContextCapsule): string {
  const governing = {
    subject: capsule.subject,
    // Sorted so ordering differences between agents are not tampering.
    constraints: capsule.constraints
      .map((c) => `${c.policyId}|${c.severity}|${c.statement}`)
      .sort(),
    decisions: capsule.decisions.map((d) => `${d.kind}|${d.summary}`).sort(),
    open_blockers: [...capsule.open_blockers].sort(),
  };
  return createHash("sha256").update(JSON.stringify(governing)).digest("hex").slice(0, 16);
}

export type IntegrityResult =
  | { ok: true; digest: string }
  | { ok: false; expected: string; actual: string; dropped: string[] };

export function verifyCapsuleIntegrity(
  capsule: ContextCapsule,
  expected: string | undefined,
  baseline?: ContextCapsule,
): IntegrityResult {
  const actual = capsuleDigest(capsule);
  if (expected && actual === expected) return { ok: true, digest: actual };

  // Name what went missing, so the failure is actionable rather than
  // just a hash mismatch.
  const dropped: string[] = [];
  if (baseline) {
    const have = new Set(capsule.constraints.map((c) => `${c.policyId}|${c.statement}`));
    for (const c of baseline.constraints) {
      const key = `${c.policyId}|${c.statement}`;
      if (!have.has(key)) dropped.push(`constraint ${c.policyId}: ${c.statement}`);
    }
    const blockers = new Set(capsule.open_blockers);
    for (const b of baseline.open_blockers) if (!blockers.has(b)) dropped.push(`blocker ${b}`);
  }

  return { ok: false, expected: expected ?? "(none carried)", actual, dropped };
}

function buildSubject(kind: "worker" | "customer" | "system", f: Facts): Record<string, unknown> {
  if (kind === "customer") {
    return {
      type: "customer",
      name: f.customerName,
      tier: f.customerTier,
      mrr_usd: f.customerMrr,
      incident: f.incidentId,
      incident_hours: f.incidentHours,
    };
  }
  if (kind === "worker") {
    return {
      type: "worker",
      name: f.subjectName,
      worker_id: f.workerId,
      employment_type: f.employmentType,
      manager: f.managerName,
      start_date: f.startDate,
      engagement_ends: f.sowEndDate,
    };
  }
  return { type: "system" };
}

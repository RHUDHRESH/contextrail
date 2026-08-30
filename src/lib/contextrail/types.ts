import { z } from "zod";

/* ------------------------------------------------------------------ *
 * ContextRail core schemas.
 * Every MCP tool boundary and every API route validates against these,
 * so a capsule produced by the UI is byte-identical to one produced by
 * an external agent calling the MCP server.
 * ------------------------------------------------------------------ */

export const SystemId = z.enum([
  "notion",
  "gdocs",
  "slack",
  "freshservice",
  "crm",
  "github",
  "linear",
  "hris",
]);
export type SystemId = z.infer<typeof SystemId>;

export const AgentId = z.enum([
  "HR_AGENT",
  "IT_PROVISIONING_AGENT",
  "SECURITY_AGENT",
  "SUPPORT_AGENT",
  "FINANCE_AGENT",
  "ENGINEERING_AGENT",
]);
export type AgentId = z.infer<typeof AgentId>;

export const RiskLevel = z.enum(["low", "medium", "high", "critical"]);
export type RiskLevel = z.infer<typeof RiskLevel>;

/** A single retrieved fact, always traceable back to the system it came from. */
export const Evidence = z.object({
  id: z.string(),
  system: SystemId,
  kind: z.enum(["document", "record", "conversation", "ticket", "asset"]),
  title: z.string(),
  /** The extract that actually justified inclusion. */
  excerpt: z.string(),
  /** Structured payload when the source is a record rather than prose. */
  data: z.record(z.any()).optional(),
  /** Retrieval score blended with source authority. 0–1. */
  confidence: z.number().min(0).max(1),
  /** ISO date the source was last edited — drives the staleness flag. */
  lastVerifiedAt: z.string(),
  /** True when the source is older than its system's freshness budget. */
  stale: z.boolean(),
  url: z.string().optional(),
});
export type Evidence = z.infer<typeof Evidence>;

/** A hard rule the plan must respect, carried with its citation. */
export const Constraint = z.object({
  id: z.string(),
  statement: z.string(),
  policyId: z.string(),
  sourceEvidenceId: z.string(),
  severity: RiskLevel,
});
export type Constraint = z.infer<typeof Constraint>;

export const Decision = z.object({
  id: z.string(),
  at: z.string(),
  actor: z.string(),
  kind: z.enum([
    "intent_resolved",
    "policy_evaluated",
    "plan_generated",
    "handoff",
    "approval_granted",
    "approval_denied",
    "action_executed",
    "action_blocked",
    "verification",
  ]),
  summary: z.string(),
  detail: z.record(z.any()).optional(),
});
export type Decision = z.infer<typeof Decision>;

export const PlannedAction = z.object({
  id: z.string(),
  title: z.string(),
  /** MCP tool that will carry this out. */
  tool: z.string(),
  agent: AgentId,
  args: z.record(z.any()),
  risk: RiskLevel,
  dependsOn: z.array(z.string()).default([]),
  approvalRequired: z.boolean(),
  approver: z.string().nullable(),
  /** Set when policy forbids the action outright. */
  blockedBy: z.string().nullable().default(null),
  rationale: z.string(),
  /** How completion will be proven after execution. */
  verification: z.string(),
  idempotencyKey: z.string(),
});
export type PlannedAction = z.infer<typeof PlannedAction>;

export const ContextCapsule = z.object({
  request_id: z.string(),
  tenant_id: z.string(),
  created_at: z.string(),
  intent: z.string(),
  intent_confidence: z.number(),
  requester: z.object({
    id: z.string(),
    name: z.string(),
    role: z.string(),
    department: z.string(),
  }),
  subject: z.record(z.any()),
  raw_request: z.string(),
  sources: z.array(Evidence),
  constraints: z.array(Constraint),
  planned_actions: z.array(z.string()),
  decisions: z.array(Decision),
  handoff_target: AgentId.nullable(),
  handoff_chain: z.array(AgentId),
  approval_required: z.boolean(),
  audit_status: z.enum(["pending", "in_review", "executing", "complete", "partial", "failed"]),
  /** Anything the capsule could not resolve — travels with the handoff. */
  open_blockers: z.array(z.string()),
  /** SHA-256 over the governance-bearing fields. A receiving agent
   *  recomputes it to prove no constraint or deny was edited in transit.
   *  Optional so runs written before digests remain readable. */
  capsule_digest: z.string().optional(),
});
export type ContextCapsule = z.infer<typeof ContextCapsule>;

export const PolicyDecision = z.object({
  policyId: z.string(),
  title: z.string(),
  effect: z.enum(["allow", "deny", "require_approval"]),
  appliesTo: z.string(),
  reason: z.string(),
  approver: z.string().nullable(),
  citation: z.object({ system: SystemId, title: z.string(), excerpt: z.string() }),
});
export type PolicyDecision = z.infer<typeof PolicyDecision>;

export const ActionPlan = z.object({
  plan_id: z.string(),
  request_id: z.string(),
  actions: z.array(PlannedAction),
  agents: z.array(AgentId),
  summary: z.string(),
  estimated_minutes_saved: z.number(),
});
export type ActionPlan = z.infer<typeof ActionPlan>;

export const ExecutionRecord = z.object({
  actionId: z.string(),
  status: z.enum(["succeeded", "failed", "skipped", "blocked", "awaiting_approval"]),
  tool: z.string(),
  agent: AgentId,
  startedAt: z.string(),
  finishedAt: z.string(),
  attempts: z.number(),
  output: z.record(z.any()).optional(),
  verified: z.boolean(),
  verification_note: z.string(),
  error: z.string().nullable().default(null),
});
export type ExecutionRecord = z.infer<typeof ExecutionRecord>;

export const Approval = z.object({
  id: z.string(),
  actionId: z.string(),
  title: z.string(),
  approver: z.string(),
  risk: RiskLevel,
  policyId: z.string(),
  why: z.string(),
  state: z.enum(["pending", "approved", "denied"]),
  decidedAt: z.string().nullable().default(null),
  note: z.string().nullable().default(null),
});
export type Approval = z.infer<typeof Approval>;

export const Run = z.object({
  id: z.string(),
  tenant_id: z.string(),
  createdAt: z.string(),
  request: z.string(),
  requesterId: z.string(),
  scenarioId: z.string().nullable(),
  capsule: ContextCapsule,
  policies: z.array(PolicyDecision),
  plan: ActionPlan,
  approvals: z.array(Approval),
  executions: z.array(ExecutionRecord),
  audit: z.array(Decision),
  status: z.enum(["assembling", "awaiting_approval", "executing", "complete", "partial", "failed"]),
  metrics: z.object({
    sources_touched: z.number(),
    evidence_count: z.number(),
    actions_total: z.number(),
    actions_completed: z.number(),
    actions_blocked: z.number(),
    handoffs: z.number(),
    minutes_saved: z.number(),
    policy_violations_prevented: z.number(),
  }),
});
export type Run = z.infer<typeof Run>;

/* --------------------------- stream events --------------------------- */

export type RailEvent =
  | { type: "stage"; stage: StageId; status: "running" | "done" | "blocked"; note: string }
  | { type: "evidence"; evidence: Evidence }
  | { type: "capsule"; capsule: ContextCapsule }
  | { type: "policy"; decision: PolicyDecision }
  | { type: "plan"; plan: ActionPlan }
  | { type: "handoff"; from: AgentId | "ORCHESTRATOR"; to: AgentId; carries: string[] }
  | { type: "approval"; approval: Approval }
  | { type: "execution"; record: ExecutionRecord }
  | { type: "audit"; decision: Decision }
  | { type: "run"; run: Run }
  | { type: "error"; message: string };

export const STAGES = [
  { id: "discover", label: "Discover", blurb: "Sweep connected knowledge" },
  { id: "compile", label: "Compile", blurb: "Build the Context Capsule" },
  { id: "govern", label: "Govern", blurb: "Apply policy and permissions" },
  { id: "plan", label: "Plan", blurb: "Generate the action plan" },
  { id: "handoff", label: "Handoff", blurb: "Route to specialist agents" },
  { id: "approve", label: "Approve", blurb: "Hold privileged actions" },
  { id: "execute", label: "Execute", blurb: "Run through MCP tools" },
  { id: "verify", label: "Verify", blurb: "Prove the outcome landed" },
] as const;

export type StageId = (typeof STAGES)[number]["id"];

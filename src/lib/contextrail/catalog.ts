/* ------------------------------------------------------------------ *
 * The public surface, documented once.
 *
 * mcp/server.ts reads `summary` from here so the tool descriptions an
 * MCP client sees and the ones rendered on /skills can never drift
 * apart. Input and output rows mirror the Zod schemas in the server.
 * ------------------------------------------------------------------ */

export type ToolDoc = {
  name: string;
  /** Which rail stage the tool belongs to. */
  stage: string;
  summary: string;
  input: Record<string, string>;
  output: Record<string, string>;
  boundary: string;
  errors: string[];
};

export const MCP_TOOLS: ToolDoc[] = [
  {
    name: "search_enterprise_knowledge",
    stage: "discover",
    summary:
      "Sweep connected enterprise sources — Notion, Google Docs, Slack, Freshservice, CRM, GitHub, Linear, HRIS — and return cited evidence with per-source confidence and a freshness verdict. Read-only; use it on its own when the request is a question rather than a task.",
    input: {
      "query: string": "Natural-language question or keywords.",
      "sources?: SystemId[]": "Restrict the sweep to these connectors.",
      "user_context?: object": "Caller identity; scopes results to what this role may see.",
    },
    output: {
      "evidence[]": "id, system, title, excerpt, confidence, lastVerifiedAt, stale",
      "coverage": "which connectors were searched, and which hits are stale",
    },
    boundary:
      "Read-only and tenant-scoped. Never returns a source below the confidence floor, and never suppresses a stale flag to make an answer look cleaner.",
    errors: ["NO_RESULTS"],
  },
  {
    name: "compile_context_capsule",
    stage: "compile",
    summary:
      "Turn a raw request into a portable, evidence-backed Context Capsule: resolved intent, subject record, cited sources, active policy constraints, and unresolved blockers. This is the artifact every other ContextRail tool consumes.",
    input: {
      "request: string": "The request, verbatim — do not pre-summarise it.",
      "user_id?: string": "Requester identity, e.g. U-2201.",
      "tenant_id?: string": "Hard isolation boundary.",
    },
    output: {
      "capsule": "the full ContextCapsule, schema-validated",
      "intent_confidence": "0–1; below 0.6 the tool refuses rather than guessing",
    },
    boundary:
      "Anchor records are fetched by identity rather than discovered by search, so the governing facts are the same whether or not the requester happened to name the subject.",
    errors: ["INTENT_AMBIGUOUS"],
  },
  {
    name: "check_policy_and_permissions",
    stage: "govern",
    summary:
      "Evaluate a proposed action against the policies that apply to this specific subject. Returns allow, deny, or require_approval — each with the named approver and the clause the verdict came from. A deny is terminal and carries no approval path.",
    input: {
      "action: { tool, args?, risk? }": "The action under consideration.",
      "context_capsule: { request_id, ... }": "A capsule, or at minimum its request_id.",
    },
    output: {
      "effect": "allow | require_approval | deny",
      "approver": "named human when the effect is require_approval, otherwise null",
      "policy_id + reason": "the rule that decided, and why",
      "citation": "{ system, title, excerpt } — the clause itself",
      "terminal": "true when no approval can override the verdict",
    },
    boundary:
      "Rejects an unknown capsule rather than guessing. Policy applicability is evaluated against the capsule's subject, never against the request's wording.",
    errors: ["CAPSULE_NOT_FOUND"],
  },
  {
    name: "generate_action_plan",
    stage: "plan",
    summary:
      "Produce an ordered, governed action plan: every action names the MCP tool that will run it, the agent that owns it, its dependencies, its approval requirement, an idempotency key, and the post-condition that will prove it landed. Actions forbidden by policy are returned as blocked, never silently dropped.",
    input: {
      "request: string": "The request to plan for; assembles a capsule if none exists.",
      "user_id?: string": "Requester identity.",
      "tenant_id?: string": "Hard isolation boundary.",
      "available_tools?: string[]": "Restrict planning to tools the caller actually has.",
    },
    output: {
      "plan.actions[]": "id, title, tool, agent, dependsOn, approvalRequired, idempotencyKey, verification",
      "approvals_required[]": "what stops for a human, and who owns each decision",
      "blocked[]": "what policy refused, with the rule that refused it",
    },
    boundary:
      "Planning is not execution — nothing here produces a side effect. A tool the caller does not have is reported as unavailable rather than planned around.",
    errors: ["PLAN_FAILED", "INTENT_AMBIGUOUS"],
  },
  {
    name: "handoff_to_specialist",
    stage: "handoff",
    summary:
      "Transfer a capsule to the specialist that owns a needed capability, carrying the original request, all evidence, active constraints, prior decisions, assigned actions, and open blockers. The receiving agent starts with everything, by value — not with a summary.",
    input: {
      "request_id: string": "The capsule to transfer.",
      "target_agent?: AgentId": "Name the specialist directly.",
      "capability?: string": "Or pass a capability and let the registry route it.",
    },
    output: {
      "handoff": "receiving agent, owner team, capabilities, available tools",
      "carries": "explicit manifest of what travelled",
      "capsule": "the updated capsule with the hop appended to handoff_chain",
    },
    boundary:
      "The chain appends and never overwrites. If no agent owns the capability the tool returns a blocker rather than improvising a fallback.",
    errors: ["CAPSULE_NOT_FOUND", "CAPABILITY_UNMATCHED"],
  },
  {
    name: "execute_and_verify",
    stage: "execute",
    summary:
      "Run approved actions through MCP integrations under idempotency keys with bounded retries, then probe each outcome against its stated post-condition. A write that returned success but fails its probe is reported unverified rather than complete.",
    input: {
      "request_id: string": "The run to execute.",
      "approvals?: { approvalId, state }[]": "Approval decisions to apply before running.",
    },
    output: {
      "records[]": "per action: status, attempts, output, verified, verification_note",
      "summary": "executed, verified, blocked, awaiting_approval, failed",
      "audit[]": "append-only ledger of actor, tool, key, and outcome",
    },
    boundary:
      "Refuses unapproved privileged actions outright rather than deferring them to a queue. Replaying a settled idempotency key returns the original result instead of acting twice.",
    errors: ["RUN_NOT_FOUND", "APPROVAL_MISSING", "EXECUTION_FAILED", "VERIFICATION_FAILED"],
  },
];

export type SkillDoc = {
  name: string;
  stage: string;
  blurb: string;
  inputs: string;
  outputs: string;
  uses: string[];
  integrations: string[];
};

export const SKILLS: SkillDoc[] = [
  {
    name: "contextrail-discover",
    stage: "discover",
    blurb:
      "Find what the company already knows, with the receipts. Ranks by relevance and source authority, and flags anything past its freshness budget instead of quoting it silently.",
    inputs: "A question, optional connector filter",
    outputs: "Cited evidence, confidence scores, staleness flags",
    uses: ["search_enterprise_knowledge"],
    integrations: ["Notion", "Google Docs", "Slack", "Freshservice", "CRM", "GitHub", "Linear", "HRIS"],
  },
  {
    name: "contextrail-compile",
    stage: "compile",
    blurb:
      "Build the capsule every downstream agent reads: resolved intent, the subject's actual record, the evidence that justified each fact, and what could not be resolved.",
    inputs: "A request in the requester's own words",
    outputs: "A schema-validated Context Capsule",
    uses: ["compile_context_capsule", "search_enterprise_knowledge"],
    integrations: ["HRIS", "CRM", "Notion", "Freshservice"],
  },
  {
    name: "contextrail-govern",
    stage: "govern",
    blurb:
      "Answer not what the policy says, but whether it applies to this person, for this action, right now — and who owns the decision. Every verdict quotes its clause.",
    inputs: "A capsule and a proposed action",
    outputs: "allow / deny / require_approval, approver, citation",
    uses: ["check_policy_and_permissions"],
    integrations: ["Notion", "Google Docs", "HRIS"],
  },
  {
    name: "contextrail-handoff",
    stage: "handoff",
    blurb:
      "Move work across a team boundary without losing context. Routes by capability, transfers the capsule by value, and carries unresolved blockers so nobody plans around them.",
    inputs: "A capsule and a target agent or capability",
    outputs: "A handoff record, a carries manifest, the updated chain",
    uses: ["handoff_to_specialist"],
    integrations: ["Any registered specialist agent"],
  },
  {
    name: "contextrail-execute",
    stage: "execute",
    blurb:
      "Do the work, then prove it was done. Idempotent writes, bounded retries, and a post-condition probe on every outcome — because a 200 is not the same as a result.",
    inputs: "A run id and its approval state",
    outputs: "Execution records, verification notes, an audit trail",
    uses: ["execute_and_verify", "generate_action_plan"],
    integrations: ["Freshservice", "Slack", "GitHub", "Linear", "Billing"],
  },
];

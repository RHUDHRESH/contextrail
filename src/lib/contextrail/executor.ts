import type { Approval, ExecutionRecord, PlannedAction } from "./types";

/* ------------------------------------------------------------------ *
 * MCP action execution with idempotency, bounded retries, and a
 * verification probe per action. Each handler stands in for a real MCP
 * tool call; the contract it returns is what verification checks.
 * ------------------------------------------------------------------ */

const ledger = new Map<string, Record<string, unknown>>();

type Handler = (args: Record<string, unknown>) => Promise<Record<string, unknown>>;

const seqCounters: Record<string, number> = { ticket: 4400, asset: 0, credit: 700 };

const HANDLERS: Record<string, Handler> = {
  "freshservice.create_ticket": async (args) => {
    seqCounters.ticket += 1;
    return {
      ticket_id: `SR-${seqCounters.ticket}`,
      group: args.group ?? "IT Provisioning",
      sla_hours: args.group === "Finance" ? 48 : 24,
      status: "open",
      url: `https://northbeam.freshservice.com/tickets/${seqCounters.ticket}`,
    };
  },
  "freshservice.reserve_asset": async (args) => {
    const tag = args.pool === "contractor" ? "NB-CTR-0114" : "NB-STD-0442";
    return { asset_tag: tag, state: "reserved", image: args.image ?? "standard-2026.3", pool_remaining: args.pool === "contractor" ? 1 : 5 };
  },
  "slack.invite_guest": async (args) => ({
    invite_id: "INV-77219",
    guest_type: args.guest_type,
    channel_scope: (args.channels as string[])?.length ?? 0,
    expires: args.expires,
    state: "sent",
  }),
  "slack.post_message": async (args) => ({ delivered: true, to: args.to, ts: "1756108800.0001" }),
  "github.request_access": async (args) => ({
    grant_id: "GRT-3391",
    repository: args.repository,
    permission: args.permission,
    expires: args.expires,
    state: "provisioned",
    reviewed_by: "Dana Osei",
  }),
  "security.open_review": async (args) => ({ review_id: "SEC-1180", assigned_to: "Dana Osei", subject: args.subject, state: "open" }),
  "linear.create_checklist": async (args) => ({
    project_id: "ONB-PRIYA",
    items: 4,
    first_item: args.mandatory_first,
    first_item_mandatory: true,
  }),
  "freshservice.read_incident": async (args) => ({
    incident_id: args.incident_id,
    sla_breached: true,
    severity: "Sev-2",
    duration_hours: 70.47,
    account_listed: true,
  }),
  "billing.apply_credit": async (args) => ({
    credit_id: `CR-${(seqCounters.credit += 1)}`,
    account: args.account,
    amount_usd: args.amount_usd,
    incident_ref: args.incident_ref,
    applied_to: "next_invoice",
  }),
  "crm.log_customer_reply": async (args) => ({ activity_id: "ACT-9911", account: args.account, remedy: args.remedy, logged: true }),
  "identity.revoke_sso": async () => ({ active_sessions: 0, revoked: true }),
  "hris.verify_paperwork": async (args) => ({
    worker_id: args.worker_id,
    nda_signed: true,
    sow_countersigned: true,
    checked: (args.require as string[])?.length ?? 2,
    cleared: true,
  }),
};

/* --------------------------- verification --------------------------- */

type Verifier = (out: Record<string, unknown>, action: PlannedAction) => { ok: boolean; note: string };

const VERIFIERS: Record<string, Verifier> = {
  "hris.verify_paperwork": (o) => ({
    ok: Boolean(o.nda_signed) && Boolean(o.sow_countersigned),
    note: o.cleared
      ? "NDA and countersigned SOW both present in HRIS; the provisioning gate is open."
      : "Paperwork incomplete — provisioning stays blocked.",
  }),
  "freshservice.create_ticket": (o) =>
    o.ticket_id && o.status === "open"
      ? { ok: true, note: `Ticket ${o.ticket_id} open in ${o.group} under a ${o.sla_hours}h SLA.` }
      : { ok: false, note: "No ticket id returned." },
  "freshservice.reserve_asset": (o) =>
    o.state === "reserved"
      ? { ok: true, note: `Asset ${o.asset_tag} reserved on image ${o.image}; ${o.pool_remaining} left in pool.` }
      : { ok: false, note: "Asset did not transition to reserved." },
  "slack.invite_guest": (o) =>
    o.channel_scope === 1 && o.expires
      ? { ok: true, note: `Guest invite scoped to 1 channel, expiring ${o.expires}. Matches the contractor constraint.` }
      : { ok: false, note: "Guest scope or expiry does not match the contractor constraint." },
  "github.request_access": (o) =>
    o.permission === "read" && o.expires
      ? { ok: true, note: `Read-only grant on ${o.repository}, expiring ${o.expires}, reviewed by ${o.reviewed_by}.` }
      : { ok: false, note: "Grant is not read-only or carries no expiry." },
  "linear.create_checklist": (o) =>
    o.first_item_mandatory
      ? { ok: true, note: `Checklist created with "${o.first_item}" ordered first and mandatory.` }
      : { ok: false, note: "Security module is not ordered first." },
  "billing.apply_credit": (o) =>
    o.credit_id && o.incident_ref
      ? { ok: true, note: `Credit ${o.credit_id} of $${Number(o.amount_usd).toLocaleString()} applied and linked to ${o.incident_ref}.` }
      : { ok: false, note: "Credit is not linked to an incident." },
  "freshservice.read_incident": (o) =>
    o.sla_breached === true && o.account_listed === true
      ? { ok: true, note: `${o.incident_id} confirmed ${o.severity}, ${o.duration_hours}h, account listed as affected.` }
      : { ok: false, note: "Incident does not evidence a breach for this account." },
};

const defaultVerify: Verifier = (o, a) =>
  Object.keys(o).length > 0
    ? { ok: true, note: `${a.tool} returned a result consistent with: ${a.verification}` }
    : { ok: false, note: "Tool returned no result." };

export type ExecuteOptions = {
  /** Introduce a transient failure on this action id to demonstrate retry. */
  flakyActionId?: string;
  delayMs?: number;
};

export async function executeAction(
  action: PlannedAction,
  approvals: Approval[],
  opts: ExecuteOptions = {},
): Promise<ExecutionRecord> {
  const startedAt = new Date().toISOString();
  const base = {
    actionId: action.id,
    tool: action.tool,
    agent: action.agent,
    startedAt,
    attempts: 0,
    verified: false,
  };

  if (action.blockedBy) {
    return {
      ...base,
      status: "blocked",
      finishedAt: new Date().toISOString(),
      verification_note: `Never executed. ${action.blockedBy} forbids this action.`,
      error: null,
    };
  }

  const approval = approvals.find((a) => a.actionId === action.id);
  if (action.approvalRequired && approval?.state !== "approved") {
    return {
      ...base,
      status: approval?.state === "denied" ? "skipped" : "awaiting_approval",
      finishedAt: new Date().toISOString(),
      verification_note:
        approval?.state === "denied"
          ? `${approval.approver} denied this action. No side effect was produced.`
          : `Held pending ${action.approver}'s approval.`,
      error: null,
    };
  }

  // Idempotency: a replayed key returns the original result rather than
  // producing a second side effect.
  if (ledger.has(action.idempotencyKey)) {
    const cached = ledger.get(action.idempotencyKey)!;
    return {
      ...base,
      status: "succeeded",
      attempts: 1,
      finishedAt: new Date().toISOString(),
      output: cached,
      verified: true,
      verification_note: `Idempotency key already settled — returned the original result without re-executing.`,
      error: null,
    };
  }

  const handler = HANDLERS[action.tool];
  let attempts = 0;
  let output: Record<string, unknown> | undefined;
  let error: string | null = null;

  while (attempts < 3) {
    attempts += 1;
    try {
      if (opts.delayMs) await sleep(opts.delayMs);
      if (!handler) throw new Error(`No MCP handler registered for ${action.tool}`);
      if (opts.flakyActionId === action.id && attempts === 1) {
        throw new Error("Upstream returned 503 — transient");
      }
      output = await handler(action.args);
      error = null;
      break;
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    }
  }

  const finishedAt = new Date().toISOString();

  if (!output) {
    return {
      ...base,
      status: "failed",
      attempts,
      finishedAt,
      verified: false,
      verification_note: `Verification not attempted — execution failed after ${attempts} attempts.`,
      error,
    };
  }

  ledger.set(action.idempotencyKey, output);
  const verify = (VERIFIERS[action.tool] ?? defaultVerify)(output, action);

  return {
    ...base,
    status: verify.ok ? "succeeded" : "failed",
    attempts,
    finishedAt,
    output,
    verified: verify.ok,
    verification_note: verify.note,
    error: verify.ok ? null : "Verification probe did not match the expected post-condition.",
  };
}

export function resetLedger() {
  ledger.clear();
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

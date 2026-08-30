import { routeCapability } from "./agents";
import type { Facts } from "./facts";
import type { GovernanceResult } from "./policy";
import type { ActionPlan, AgentId, ContextCapsule, PlannedAction, RiskLevel } from "./types";

/* ------------------------------------------------------------------ *
 * The action planner. Templates describe what a workflow *could* do;
 * governance decides what survives. An action whose key is forbidden
 * is emitted as blocked rather than dropped, so the interface can show
 * the user what was prevented and which policy prevented it.
 * ------------------------------------------------------------------ */

type ActionTemplate = {
  key: string;
  title: (f: Facts) => string;
  tool: string;
  capability: string;
  risk: RiskLevel;
  args: (f: Facts) => Record<string, unknown>;
  rationale: (f: Facts) => string;
  verification: string;
  dependsOn?: string[];
  minutesSaved: number;
  /** Skip the action entirely when the precondition fails. */
  include?: (f: Facts) => boolean;
};

const TEMPLATES: Record<string, ActionTemplate[]> = {
  contractor_onboarding: [
    {
      key: "verify_paperwork",
      title: (f) => `Verify NDA and countersigned SOW for ${f.subjectName ?? "the starter"}`,
      tool: "hris.verify_paperwork",
      capability: "paperwork_verification",
      risk: "low",
      minutesSaved: 10,
      args: (f) => ({ worker_id: f.workerId, require: ["nda", "sow_countersigned"] }),
      rationale: (f) =>
        f.ndaSigned && f.sowCountersigned
          ? "Policy blocks all provisioning until paperwork is complete, so HR clears the gate before IT touches anything."
          : "Paperwork is incomplete — every downstream provisioning action stays blocked until HR resolves it.",
      verification: "HRIS reports both nda_signed and sow_countersigned true against the worker record.",
    },
    {
      key: "create_onboarding_ticket",
      title: (f) => `Open onboarding ticket for ${f.subjectName ?? "the starter"}`,
      tool: "freshservice.create_ticket",
      capability: "ticketing",
      risk: "low",
      minutesSaved: 12,
      args: (f) => ({
        catalog_item: "CAT-ONB-01",
        subject: `Contractor onboarding — ${f.subjectName}`,
        group: "IT Provisioning",
        due: f.startDate,
        worker_id: f.workerId,
      }),
      dependsOn: ["verify_paperwork"],
      rationale: () => "The service catalogue routes new-starter onboarding to IT Provisioning under a 24-hour SLA.",
      verification: "Ticket exists in Freshservice with group=IT Provisioning and a due date on or before the start date.",
    },
    {
      key: "reserve_laptop",
      title: (f) => `Reserve a contractor-pool laptop (${f.contractorLaptopsAvailable ?? 0} available)`,
      tool: "freshservice.reserve_asset",
      capability: "asset_allocation",
      risk: "low",
      minutesSaved: 18,
      dependsOn: ["create_onboarding_ticket"],
      args: (f) => ({ pool: "contractor", image: "contractor-restricted-2026.3", assign_to: f.workerId }),
      rationale: () =>
        "Contractor policy requires pool hardware rather than a new purchase, and the pool currently has stock.",
      verification: "Asset tag is transitioned to reserved and bound to the worker record.",
    },
    {
      key: "provision_slack_guest",
      title: (f) => `Invite ${f.subjectName ?? "the starter"} to Slack as a single-channel guest`,
      tool: "slack.invite_guest",
      capability: "identity_provisioning",
      risk: "low",
      minutesSaved: 8,
      dependsOn: ["create_onboarding_ticket"],
      args: (f) => ({ guest_type: "single_channel", channels: ["#perception"], expires: f.sowEndDate, worker_id: f.workerId }),
      rationale: () => "Contractors receive guest access scoped to the engaging team's channels, expiring with the SOW.",
      verification: "Slack returns a guest invitation with a channel scope of exactly one channel and a set expiry.",
    },
    {
      key: "request_github_access",
      title: (f) => `Request read-only access to ${f.sowRepositories[0] ?? "the SOW repository"}`,
      tool: "github.request_access",
      capability: "privilege_grant",
      risk: "high",
      minutesSaved: 25,
      args: (f) => ({
        repository: f.sowRepositories[0] ?? null,
        permission: "read",
        expires: f.sowEndDate,
        justification: `SOW-named repository for ${f.subjectName} (${f.workerId})`,
      }),
      rationale: (f) =>
        `${f.sowRepositories[0]} is tagged production, so the Access Control Standard routes the grant to Security on-call before provisioning.`,
      verification: "Security review record exists and the resulting grant is read-only with an expiry equal to the SOW end date.",
    },
    {
      key: "grant_production_credentials",
      title: () => "Issue production database credentials",
      tool: "vault.issue_credential",
      capability: "privilege_grant",
      risk: "critical",
      minutesSaved: 0,
      args: (f) => ({ scope: "production", worker_id: f.workerId }),
      rationale: () => "Requested as part of a blanket 'everything she needs' provisioning ask.",
      verification: "Not applicable — the action never reaches execution.",
    },
    {
      key: "create_onboarding_checklist",
      title: (f) => `Create the engineering onboarding checklist for ${f.subjectName ?? "the starter"}`,
      tool: "linear.create_checklist",
      capability: "onboarding_orchestration",
      risk: "low",
      minutesSaved: 15,
      dependsOn: ["create_onboarding_ticket"],
      args: (f) => ({
        template: "engineering-onboarding",
        assignee: f.workerId,
        mandatory_first: "Complete security awareness module",
      }),
      rationale: () =>
        "The onboarding template orders the mandatory security module ahead of repository activation for contractors.",
      verification: "Checklist exists with the security awareness item ordered first and marked mandatory.",
    },
    {
      key: "notify_manager",
      title: (f) => `Brief ${f.managerName ?? "the manager"} on what was provisioned and what was withheld`,
      tool: "slack.post_message",
      capability: "onboarding_orchestration",
      risk: "low",
      minutesSaved: 10,
      dependsOn: ["reserve_laptop", "provision_slack_guest", "create_onboarding_checklist"],
      args: (f) => ({ to: f.managerName, summary: "contractor onboarding outcome" }),
      rationale: () => "The requester needs the blocked items in writing to act on them before the start date.",
      verification: "Message delivered to the manager with the blocked-item list attached.",
    },
  ],

  employee_onboarding: [
    {
      key: "create_onboarding_ticket",
      title: (f) => `Open onboarding ticket for ${f.subjectName ?? "the starter"}`,
      tool: "freshservice.create_ticket",
      capability: "ticketing",
      risk: "low",
      minutesSaved: 12,
      args: (f) => ({ catalog_item: "CAT-ONB-01", group: "IT Provisioning", worker_id: f.workerId }),
      rationale: () => "Standard new-starter route.",
      verification: "Ticket exists with the IT Provisioning group.",
    },
    {
      key: "reserve_laptop",
      title: (f) => `Allocate a standard engineering laptop (${f.standardLaptopsAvailable ?? 0} available)`,
      tool: "freshservice.reserve_asset",
      capability: "asset_allocation",
      risk: "low",
      minutesSaved: 18,
      args: () => ({ pool: "standard" }),
      rationale: () => "Full-time employees draw from the standard catalogue.",
      verification: "Asset reserved from the standard pool.",
    },
  ],

  service_credit_request: [
    {
      key: "confirm_eligibility",
      title: (f) => `Confirm SLA breach eligibility against ${f.incidentId ?? "the incident"}`,
      tool: "freshservice.read_incident",
      capability: "eligibility_assessment",
      risk: "low",
      minutesSaved: 20,
      args: (f) => ({ incident_id: f.incidentId, account: f.customerName }),
      rationale: (f) =>
        `${f.incidentId} is a confirmed ${f.incidentSeverity} of ${f.incidentHours?.toFixed(1)}h against a ${f.customerTier} SLA.`,
      verification: "Incident record shows sla_breached=true and the account is listed among those affected.",
    },
    {
      key: "issue_cash_refund",
      title: () => "Issue a cash refund to the customer",
      tool: "billing.refund",
      capability: "credit_issuance",
      risk: "critical",
      minutesSaved: 0,
      args: (f) => ({ account: f.customerName, amount_usd: f.computedCreditUsd }),
      rationale: () => "Requested explicitly by the customer.",
      verification: "Not applicable — the action never reaches execution.",
    },
    {
      key: "issue_service_credit",
      title: (f) => `Apply a $${(f.computedCreditUsd ?? 0).toLocaleString()} service credit`,
      tool: "billing.apply_credit",
      capability: "credit_issuance",
      risk: "high",
      minutesSaved: 22,
      dependsOn: ["confirm_eligibility"],
      args: (f) => ({
        account: f.customerName,
        amount_usd: f.computedCreditUsd,
        incident_ref: f.incidentId,
        remedy_type: "service_credit",
      }),
      rationale: (f) =>
        `${f.customerTier} schedule computes $${f.computedCreditUsd?.toLocaleString()} for ${Math.floor((f.incidentHours ?? 0) / 24)} qualifying day(s), inside the cap.`,
      verification: "Credit line appears on the account and references the incident ID.",
    },
    {
      key: "create_billing_ticket",
      title: (f) => `Open a billing adjustment ticket for ${f.customerName ?? "the account"}`,
      tool: "freshservice.create_ticket",
      // Routed by what the ticket does, not by the fact that it is a ticket —
      // the service catalogue sends billing adjustments to Finance, not IT.
      capability: "billing_adjustment",
      risk: "low",
      minutesSaved: 10,
      dependsOn: ["confirm_eligibility"],
      args: (f) => ({ catalog_item: "CAT-BIL-02", group: "Finance", account: f.customerName, incident_ref: f.incidentId }),
      rationale: () => "The catalogue routes billing adjustments to Finance with a 48-hour SLA.",
      verification: "Ticket exists in the Finance group and links the incident.",
    },
    {
      key: "reply_to_customer",
      title: (f) => `Send ${f.customerName ?? "the customer"} the remedy explanation`,
      tool: "crm.log_customer_reply",
      capability: "customer_comms",
      risk: "medium",
      minutesSaved: 14,
      dependsOn: ["issue_service_credit"],
      args: (f) => ({ account: f.customerName, remedy: "service_credit", amount_usd: f.computedCreditUsd }),
      rationale: () =>
        "The customer asked for a cash refund; the reply must explain the contractual remedy rather than restate a refusal.",
      verification: "Reply logged against the account with the credit amount and incident reference.",
    },
  ],

  access_request: [
    {
      key: "grant_write_access",
      title: (f) => `Grant write access to ${f.requestedRepositories[0] ?? "the requested repository"}`,
      tool: "github.add_collaborator",
      capability: "privilege_grant",
      risk: "critical",
      minutesSaved: 0,
      args: (f) => ({ repository: f.requestedRepositories[0] ?? null, permission: "write", worker_id: f.workerId }),
      rationale: (f) =>
        `Requested verbatim: write access to ${f.requestedRepositories[0] ?? "a repository"}. ${f.subjectName ?? "The subject"} is a ${f.employmentType ?? "worker"}, and contractor repository access is read-only.`,
      verification: "Not applicable — the action never reaches execution.",
    },
    {
      key: "request_github_access",
      title: (f) => `Open a Security review for ${f.requestedRepositories[0] ?? "the requested repository"}`,
      tool: "security.open_review",
      capability: "access_review",
      risk: "high",
      minutesSaved: 25,
      args: (f) => ({ repository: f.requestedRepositories[0], subject: f.subjectName }),
      rationale: () => "All third-party and production-tagged grants route through Security on-call.",
      verification: "Review record created and assigned to Security on-call.",
    },
  ],

  offboarding: [
    {
      key: "revoke_sso",
      title: (f) => `Revoke SSO for ${f.subjectName ?? "the leaver"}`,
      tool: "identity.revoke_sso",
      capability: "credential_rotation",
      risk: "high",
      minutesSaved: 15,
      args: (f) => ({ worker_id: f.workerId }),
      rationale: () => "The runbook requires revocation within four hours of the termination timestamp.",
      verification: "Identity provider reports zero active sessions for the worker.",
    },
    {
      key: "reclaim_asset",
      title: () => "Raise the hardware reclaim ticket",
      tool: "freshservice.create_ticket",
      capability: "ticketing",
      risk: "low",
      minutesSaved: 10,
      args: (f) => ({ worker_id: f.workerId, type: "asset_reclaim" }),
      rationale: () => "Hardware reclaim is tracked through Freshservice.",
      verification: "Reclaim ticket exists and is linked to the asset tag.",
    },
  ],
};

export function generateActionPlan(
  capsule: ContextCapsule,
  facts: Facts,
  governance: GovernanceResult,
  entryAgent: AgentId,
): ActionPlan {
  const templates = TEMPLATES[capsule.intent] ?? [];
  const actions: PlannedAction[] = [];

  for (const t of templates) {
    if (t.include && !t.include(facts)) continue;

    // A blanket deny ("*") stops everything; otherwise the block is
    // attributed to the rule that named this specific action key, so the
    // citation shown to the user is the one that actually refused it.
    const denyRule = governance.forbidden.get("*") ?? governance.forbidden.get(t.key);
    const forbidden = Boolean(denyRule);
    const gate = governance.gated.get(t.key);

    actions.push({
      id: `ACT-${String(actions.length + 1).padStart(2, "0")}`,
      title: t.title(facts),
      tool: t.tool,
      agent: routeCapability(t.capability, entryAgent),
      args: t.args(facts),
      risk: t.risk,
      dependsOn: (t.dependsOn ?? []).map(
        (k) => `ACT-${String(templates.filter((x) => !x.include || x.include(facts)).findIndex((x) => x.key === k) + 1).padStart(2, "0")}`,
      ),
      approvalRequired: Boolean(gate) && !forbidden,
      approver: gate?.approver ?? null,
      blockedBy: denyRule?.policyId ?? null,
      rationale: denyRule?.reason ?? t.rationale(facts),
      verification: t.verification,
      idempotencyKey: `${capsule.request_id}:${t.key}`,
    });
  }

  const agents = [...new Set(actions.filter((a) => !a.blockedBy).map((a) => a.agent))];
  const minutes = templates
    .filter((t) => {
      const a = actions.find((x) => x.idempotencyKey.endsWith(`:${t.key}`));
      return a && !a.blockedBy;
    })
    .reduce((sum, t) => sum + t.minutesSaved, 0);

  const blocked = actions.filter((a) => a.blockedBy).length;
  const gated = actions.filter((a) => a.approvalRequired).length;

  return {
    plan_id: `PLAN-${capsule.request_id.replace("REQ-", "")}`,
    request_id: capsule.request_id,
    actions,
    agents,
    summary: `${actions.length - blocked} executable action(s) across ${agents.length} agent(s); ${gated} held for approval, ${blocked} blocked by policy.`,
    estimated_minutes_saved: minutes,
  };
}

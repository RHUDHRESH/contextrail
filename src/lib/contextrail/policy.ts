import type { Evidence, PolicyDecision, RiskLevel, SystemId } from "./types";
import { excerptFor } from "./retrieval";
import type { Facts } from "./facts";

/* ------------------------------------------------------------------ *
 * The governance layer. Every rule is declarative, cites the document
 * it came from, and returns one of three effects. Nothing in the rail
 * executes without a matching allow or an approved require_approval.
 * ------------------------------------------------------------------ */

export type PolicyRule = {
  id: string;
  title: string;
  family: string;
  /** Extra terms used to select the clause this policy quotes. */
  citationTerms?: string[];
  severity: RiskLevel;
  sourceEvidenceId: string;
  /** Runs only when the rule's subject is present in the capsule. */
  applies: (f: Facts, intent: string) => boolean;
  evaluate: (f: Facts) => {
    effect: PolicyDecision["effect"];
    appliesTo: string;
    reason: string;
    approver: string | null;
    /** Actions this rule forbids outright, matched by planner action key. */
    forbids?: string[];
    /** Actions this rule gates behind approval. */
    gates?: string[];
    constraint?: string;
  };
};

export const POLICIES: PolicyRule[] = [
  {
    id: "POL-CTR-001",
    citationTerms: ["production credentials", "database", "PII export", "forbidden", "non-employee"],
    title: "Contractors cannot receive production credentials",
    family: "access_control",
    severity: "critical",
    sourceEvidenceId: "ntn_contractor_onboarding",
    applies: (f) => f.employmentType === "contractor",
    evaluate: (f) => ({
      effect: "deny",
      appliesTo: `${f.subjectName ?? "subject"} (contractor)`,
      reason:
        "Contractor Onboarding Policy §4 forbids production credentials, production database access, and customer PII exports for non-employees. No approval path exists for this grant.",
      approver: null,
      forbids: ["grant_production_credentials", "export_customer_data"],
      constraint: "Contractors cannot receive production credentials",
    }),
  },
  {
    id: "POL-CTR-002",
    citationTerms: ["repository", "read-only", "statement of work", "github"],
    title: "Contractor repository access is read-only and scoped to the SOW",
    family: "access_control",
    severity: "high",
    sourceEvidenceId: "ntn_contractor_onboarding",
    applies: (f) => f.employmentType === "contractor" && f.sowRepositories.length > 0,
    evaluate: (f) => ({
      effect: "require_approval",
      appliesTo: f.sowRepositories.join(", "),
      reason: `Repository access for contractors is read-only and limited to repositories named in the SOW (${f.sowRepositories.join(", ")}). ${
        f.sowRepositories.some((r) => f.productionRepositories.includes(r))
          ? "This repository is tagged production, so the Access Control Standard additionally requires Security on-call approval before provisioning."
          : "Security review is still required for any third-party grant."
      }`,
      approver: f.approvers.security_on_call ?? "Security on-call",
      // Read-only is escalatable; write is not. A deny cannot be approved away.
      forbids: ["grant_write_access"],
      gates: ["request_github_access"],
      constraint: "GitHub access requires Security approval and is read-only for contractors",
    }),
  },
  {
    id: "POL-CTR-003",
    citationTerms: ["hardware", "loaner pool", "laptop", "purchase"],
    title: "Contractors use pool hardware, not new purchases",
    family: "onboarding",
    severity: "medium",
    sourceEvidenceId: "ntn_contractor_onboarding",
    applies: (f) => f.employmentType === "contractor",
    evaluate: (f) => ({
      effect: (f.contractorLaptopsAvailable ?? 0) > 0 ? "allow" : "require_approval",
      appliesTo: "Hardware allocation",
      reason:
        (f.contractorLaptopsAvailable ?? 0) > 0
          ? `Contractor pool has ${f.contractorLaptopsAvailable} available unit(s); reserving from the pool satisfies the policy without a purchase.`
          : "Contractor pool is empty. Purchasing new hardware for a contractor requires Finance approval.",
      approver: (f.contractorLaptopsAvailable ?? 0) > 0 ? null : f.approvers.finance_approver ?? "Finance",
      gates: (f.contractorLaptopsAvailable ?? 0) > 0 ? [] : ["reserve_laptop"],
      constraint: "Contractor hardware must come from the contractor loaner pool",
    }),
  },
  {
    id: "POL-CTR-004",
    citationTerms: ["slack", "single-channel guest", "workspace"],
    title: "Slack access for contractors is single-channel guest",
    family: "onboarding",
    severity: "medium",
    sourceEvidenceId: "ntn_contractor_onboarding",
    applies: (f) => f.employmentType === "contractor",
    evaluate: () => ({
      effect: "allow",
      appliesTo: "Slack workspace",
      reason:
        "Contractor Onboarding Policy §2 permits a single-channel guest account scoped to the engaging team's project channels. Full workspace membership is withheld.",
      approver: null,
      constraint: "Slack access is limited to single-channel guest on team project channels",
    }),
  },
  {
    id: "POL-CTR-005",
    citationTerms: ["NDA", "countersigned", "paperwork", "before provisioning"],
    title: "Paperwork must be complete before any provisioning",
    family: "onboarding",
    severity: "critical",
    sourceEvidenceId: "ntn_contractor_onboarding",
    applies: (f) => f.employmentType === "contractor",
    evaluate: (f) => {
      const ok = f.ndaSigned === true && f.sowCountersigned === true;
      return {
        effect: ok ? "allow" : "deny",
        appliesTo: "All provisioning actions",
        reason: ok
          ? "NDA signed and SOW countersigned in the HRIS. The precondition for provisioning is met."
          : "NDA or countersigned SOW is missing in the HRIS. Policy §5 blocks all provisioning until both exist.",
        approver: null,
        forbids: ok ? [] : ["*"],
        constraint: "NDA and countersigned SOW must exist before provisioning",
      };
    },
  },
  {
    id: "POL-ACC-010",
    citationTerms: ["expiry", "owner", "grant", "expires"],
    title: "Every grant carries an owner and an expiry",
    family: "access_control",
    severity: "medium",
    sourceEvidenceId: "ntn_access_control",
    applies: (f, intent) => intent.includes("onboarding") || intent === "access_request",
    evaluate: (f) => ({
      effect: "allow",
      appliesTo: "All access grants",
      reason: `Least Privilege Standard requires an owner, a justification, and an expiry on every grant. Expiry is set to the SOW end date${
        f.sowEndDate ? ` (${f.sowEndDate})` : ""
      } with zero grace days.`,
      approver: null,
      constraint: `All access expires ${f.sowEndDate ?? "at engagement end"} with no grace period`,
    }),
  },
  {
    id: "POL-ONB-020",
    citationTerms: ["security awareness", "module", "training"],
    title: "Security awareness module precedes repository activation",
    family: "onboarding",
    severity: "medium",
    sourceEvidenceId: "lin_onboarding_template",
    applies: (f) => f.employmentType === "contractor",
    evaluate: () => ({
      effect: "allow",
      appliesTo: "Onboarding checklist",
      reason:
        "The engineering onboarding template marks the security awareness module mandatory for contractors before repository access is activated. The checklist action is ordered ahead of access activation.",
      approver: null,
      constraint: "Security awareness module must complete before repository access activates",
    }),
  },

  /* ------------------------------- refund ------------------------------ */
  {
    id: "POL-REF-001",
    citationTerms: ["refund", "cash", "contract clause"],
    title: "SLA remedy is service credit, not cash",
    family: "refund",
    severity: "high",
    sourceEvidenceId: "ntn_refund_policy",
    applies: (f, intent) => intent === "service_credit_request",
    evaluate: (f) => ({
      effect: f.requestsCashRefund && f.contractHasRefundClause === false ? "deny" : "allow",
      appliesTo: `${f.customerName ?? "Customer"} — remedy type`,
      reason:
        f.contractHasRefundClause === false
          ? `Refund Policy §4 limits the SLA remedy to service credit. ${f.customerName ?? "The account"}'s contract contains no explicit cash refund clause, so a cash refund cannot be issued. A service credit is the permitted remedy.`
          : "The contract contains an explicit refund clause, so a cash refund is permitted.",
      approver: null,
      forbids: f.contractHasRefundClause === false ? ["issue_cash_refund"] : [],
      constraint: "Remedy must be a service credit — contract has no cash refund clause",
    }),
  },
  {
    id: "POL-REF-002",
    citationTerms: ["service credit", "eligibility", "SLA breach"],
    title: "Credit eligibility requires a confirmed Sev-1 or Sev-2 SLA breach",
    family: "refund",
    severity: "high",
    sourceEvidenceId: "ntn_refund_policy",
    applies: (f, intent) => intent === "service_credit_request",
    evaluate: (f) => {
      const eligible = f.slaBreached === true && ["Sev-1", "Sev-2"].includes(f.incidentSeverity ?? "");
      return {
        effect: eligible ? "allow" : "deny",
        appliesTo: f.incidentId ?? "Incident",
        reason: eligible
          ? `${f.incidentId} is a confirmed ${f.incidentSeverity} lasting ${f.incidentHours?.toFixed(1)}h against a ${f.customerTier} SLA. The breach qualifies for a credit.`
          : "No confirmed Sev-1 or Sev-2 SLA breach is attached to this account for the stated period, so no credit is owed.",
        approver: null,
        forbids: eligible ? [] : ["issue_service_credit"],
        constraint: eligible ? `Credit must reference ${f.incidentId}` : "No qualifying SLA breach found",
      };
    },
  },
  {
    id: "POL-REF-003",
    citationTerms: ["credit", "cap", "monthly"],
    title: "Credit value follows the tier schedule and cap",
    family: "refund",
    severity: "medium",
    sourceEvidenceId: "ntn_refund_policy",
    applies: (f, intent) => intent === "service_credit_request" && f.computedCreditUsd !== null,
    evaluate: (f) => ({
      effect: "allow",
      appliesTo: `${f.customerTier} tier schedule`,
      reason: `${f.customerTier} credits accrue at ${((f.creditRatePerDay ?? 0) * 100).toFixed(0)}% of MRR per qualifying day, capped at ${((f.creditCapRatio ?? 0) * 100).toFixed(0)}% of MRR. ${Math.floor(
        (f.incidentHours ?? 0) / 24,
      )} qualifying day(s) against $${f.customerMrr?.toLocaleString()} MRR computes to $${f.computedCreditUsd?.toLocaleString()}.`,
      approver: null,
      constraint: `Credit is fixed at $${f.computedCreditUsd?.toLocaleString()} by the tier schedule`,
    }),
  },
  {
    id: "POL-FIN-004",
    citationTerms: ["approval", "threshold", "finance"],
    title: "Credits above $2,000 require Finance approval",
    family: "finance_approval",
    severity: "high",
    sourceEvidenceId: "ntn_refund_policy",
    applies: (f, intent) => intent === "service_credit_request" && f.computedCreditUsd !== null,
    evaluate: (f) => {
      const amount = f.computedCreditUsd ?? 0;
      const tierApprover =
        amount > 10_000 ? f.approvers.vp_finance : amount > 2_000 ? f.approvers.finance_approver : null;
      return {
        effect: tierApprover ? "require_approval" : "allow",
        appliesTo: `$${amount.toLocaleString()} service credit`,
        reason: tierApprover
          ? `$${amount.toLocaleString()} exceeds the ${amount > 10_000 ? "$10,000 VP" : "$2,000 Support"} threshold. Sign-off from ${tierApprover} is required before the credit is applied.`
          : `$${amount.toLocaleString()} is within the Support issuing limit of $2,000.`,
        approver: tierApprover ?? null,
        gates: tierApprover ? ["issue_service_credit"] : [],
        constraint: tierApprover ? `Credit requires ${tierApprover}'s approval` : undefined,
      };
    },
  },

  /* ----------------------------- offboarding --------------------------- */
  {
    id: "POL-OFF-001",
    citationTerms: ["revoke", "termination", "sso", "session"],
    title: "Access revocation completes within 4 hours",
    family: "offboarding",
    severity: "critical",
    sourceEvidenceId: "ntn_offboarding",
    applies: (_f, intent) => intent === "offboarding",
    evaluate: () => ({
      effect: "allow",
      appliesTo: "All revocation actions",
      reason:
        "The Offboarding Runbook requires SSO revocation, repository removal, and credential rotation to complete within 4 hours of the termination timestamp.",
      approver: null,
      constraint: "Revocation must complete within 4 hours of termination",
    }),
  },
];

export type GovernanceResult = {
  decisions: PolicyDecision[];
  /** action key → the rule that forbade it, so a block cites the rule that made it. */
  forbidden: Map<string, { policyId: string; reason: string }>;
  gated: Map<string, { policyId: string; approver: string; reason: string; severity: RiskLevel }>;
  constraints: { statement: string; policyId: string; sourceEvidenceId: string; severity: RiskLevel }[];
};

export function evaluatePolicies(
  facts: Facts,
  intent: string,
  families: string[],
  evidence: Evidence[],
  /** Policy ids to hold out — used by the policy simulator to answer
   *  "what would this run do if this rule did not exist?". Never set in
   *  a real run. */
  disabled?: ReadonlySet<string>,
): GovernanceResult {
  const decisions: PolicyDecision[] = [];
  const forbidden = new Map<string, { policyId: string; reason: string }>();
  const gated = new Map<string, { policyId: string; approver: string; reason: string; severity: RiskLevel }>();
  const constraints: GovernanceResult["constraints"] = [];

  for (const rule of POLICIES) {
    if (disabled?.has(rule.id)) continue;
    if (!families.includes(rule.family)) continue;
    if (!rule.applies(facts, intent)) continue;

    const out = rule.evaluate(facts);
    const src = evidence.find((e) => e.id === rule.sourceEvidenceId);

    decisions.push({
      policyId: rule.id,
      title: rule.title,
      effect: out.effect,
      appliesTo: out.appliesTo,
      reason: out.reason,
      approver: out.approver,
      citation: {
        system: (src?.system ?? "notion") as SystemId,
        title: src?.title ?? rule.sourceEvidenceId,
        // Quote the sentence that supports *this* policy, not the one that
        // happened to match the user's query.
        excerpt:
          excerptFor(rule.sourceEvidenceId, [rule.title, ...(rule.citationTerms ?? [])]) ??
          src?.excerpt ??
          "Source document not present in this retrieval set.",
      },
    });

    out.forbids?.forEach((a) => forbidden.set(a, { policyId: rule.id, reason: out.reason }));
    out.gates?.forEach((a) =>
      gated.set(a, {
        policyId: rule.id,
        approver: out.approver ?? "Approver",
        reason: out.reason,
        severity: rule.severity,
      }),
    );
    if (out.constraint) {
      constraints.push({
        statement: out.constraint,
        policyId: rule.id,
        sourceEvidenceId: rule.sourceEvidenceId,
        severity: rule.severity,
      });
    }
  }

  return { decisions, forbidden, gated, constraints };
}

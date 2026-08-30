import type { AgentId, SystemId } from "./types";
import { tokenize } from "./retrieval";

/* ------------------------------------------------------------------ *
 * Intent resolution. A request is matched against a registry of known
 * workflows; the winning intent decides which systems get searched,
 * which policy families apply, and which agent owns the first leg.
 * ------------------------------------------------------------------ */

export type IntentDef = {
  id: string;
  label: string;
  description: string;
  /** Terms that raise confidence, weighted. */
  signals: Record<string, number>;
  /** Terms that rule the intent out. */
  antiSignals?: string[];
  sources: SystemId[];
  policyFamilies: string[];
  entryAgent: AgentId;
  subjectKind: "worker" | "customer" | "system";
  /**
   * Records this workflow always needs, fetched by id rather than found by
   * search. Without these, a paraphrase that omits the subject's name would be
   * governed by whichever documents happened to rank.
   */
  anchors: string[];
};

export const INTENTS: IntentDef[] = [
  {
    id: "contractor_onboarding",
    label: "Contractor onboarding",
    description: "Provision equipment, identity, tooling and a checklist for a non-employee starter.",
    signals: {
      contractor: 3, onboard: 3, onboarding: 3, joins: 2.5, starter: 2, laptop: 2,
      slack: 1.5, github: 1.5, access: 1.2, monday: 1.2, provision: 2, checklist: 1.4, hire: 1.5,
    },
    sources: ["notion", "hris", "freshservice", "gdocs", "slack", "github", "linear"],
    policyFamilies: ["onboarding", "access_control"],
    entryAgent: "HR_AGENT",
    subjectKind: "worker",
    anchors: ["hris_priya", "fs_asset_pool", "gh_repos", "ntn_contractor_onboarding"],
  },
  {
    id: "employee_onboarding",
    label: "Employee onboarding",
    description: "Provision a full-time starter with standard equipment and access.",
    signals: { employee: 3, "full-time": 3, fulltime: 3, onboard: 2.5, joins: 2, laptop: 1.6, staff: 2 },
    antiSignals: ["contractor", "vendor"],
    sources: ["notion", "hris", "freshservice", "linear"],
    policyFamilies: ["onboarding", "access_control"],
    entryAgent: "HR_AGENT",
    subjectKind: "worker",
    anchors: ["hris_priya", "fs_asset_pool"],
  },
  {
    id: "service_credit_request",
    label: "Refund / service credit",
    description: "Assess an SLA-breach remedy against contract tier and incident history.",
    signals: {
      refund: 3.2, credit: 2.6, outage: 3, downtime: 2.4, sla: 2.4, incident: 2, customer: 1.6,
      billing: 1.6, compensation: 2, money: 1.4, breach: 1.8, days: 1.0,
    },
    sources: ["notion", "crm", "freshservice", "slack"],
    policyFamilies: ["refund", "finance_approval"],
    entryAgent: "SUPPORT_AGENT",
    subjectKind: "customer",
    anchors: ["crm_meridian", "crm_tier_matrix", "fs_inc_2481"],
  },
  {
    id: "access_request",
    label: "Access request",
    description: "Grant or extend access to a system, repository, or elevated role.",
    signals: { access: 3, permission: 2.6, repository: 2.4, repo: 2.4, grant: 2.2, credentials: 2, role: 1.6 },
    antiSignals: ["onboard", "joins"],
    sources: ["notion", "gdocs", "github", "hris", "slack"],
    policyFamilies: ["access_control"],
    entryAgent: "SECURITY_AGENT",
    subjectKind: "worker",
    anchors: ["hris_priya", "gh_repos"],
  },
  {
    id: "offboarding",
    label: "Offboarding",
    description: "Revoke access, reclaim assets, and transfer ownership when someone leaves.",
    signals: { offboard: 3.4, offboarding: 3.4, leaving: 3, departure: 3, revoke: 2.6, "last day": 2.6, terminate: 2.6 },
    sources: ["notion", "hris", "freshservice", "github"],
    policyFamilies: ["offboarding", "access_control"],
    entryAgent: "HR_AGENT",
    subjectKind: "worker",
    anchors: ["hris_priya"],
  },
];

export type IntentMatch = {
  intent: IntentDef;
  confidence: number;
  runnerUp: { id: string; confidence: number } | null;
  matchedSignals: string[];
};

export function resolveIntent(request: string): IntentMatch {
  const text = request.toLowerCase();
  const tokens = new Set(tokenize(request));

  const scored = INTENTS.map((intent) => {
    let score = 0;
    const matched: string[] = [];
    for (const [signal, weight] of Object.entries(intent.signals)) {
      const hit = signal.includes(" ") ? text.includes(signal) : tokens.has(signal) || text.includes(signal);
      if (hit) {
        score += weight;
        matched.push(signal);
      }
    }
    for (const anti of intent.antiSignals ?? []) {
      if (text.includes(anti)) score -= 4;
    }
    return { intent, score: Math.max(0, score), matched };
  }).sort((a, b) => b.score - a.score);

  const top = scored[0];
  const second = scored[1];
  const total = scored.reduce((a, s) => a + s.score, 0) || 1;
  // Confidence is the winner's share of total evidence, floored so a weak
  // but unambiguous match still reads as a real decision.
  const confidence = Number(Math.min(0.99, 0.45 + (top.score / total) * 0.6).toFixed(2));

  return {
    intent: top.score > 0 ? top.intent : INTENTS[0],
    confidence: top.score > 0 ? confidence : 0.42,
    runnerUp: second && second.score > 0 ? { id: second.intent.id, confidence: Number((second.score / total).toFixed(2)) } : null,
    matchedSignals: top.matched,
  };
}

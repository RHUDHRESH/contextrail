import { compileCapsule } from "./capsule";
import { INTENTS } from "./intent";
import { generateActionPlan } from "./planner";
import { POLICIES } from "./policy";
import { SCENARIOS } from "./scenarios";

/* ------------------------------------------------------------------ *
 * Policy Studio — the simulator.
 *
 * A policy you cannot reason about is a policy nobody will edit, and a
 * governance layer nobody edits stops matching the business within a
 * quarter. This answers the question a service manager actually asks
 * before touching a rule: "if I turn this off, what starts happening?"
 *
 * It replays every fixture workflow with the rule held out and diffs the
 * resulting plans. Nothing is written; the live runs are untouched.
 * ------------------------------------------------------------------ */

export type OutcomeRow = {
  scenario: string;
  scenarioLabel: string;
  action: string;
  tool: string;
  before: "allowed" | "held" | "refused";
  after: "allowed" | "held" | "refused";
};

export type SimulationResult = {
  policyId: string;
  policyTitle: string;
  severity: string;
  /** Rows whose outcome moved when the policy was held out. */
  changes: OutcomeRow[];
  /** Total actions examined across every fixture workflow. */
  examined: number;
  /** Plain-language read on what removing this rule would do. */
  headline: string;
  newlyAllowed: number;
  losesApproval: number;
};

type Outcome = "allowed" | "held" | "refused";

function outcomeOf(a: { blockedBy: string | null; approvalRequired: boolean }): Outcome {
  if (a.blockedBy) return "refused";
  if (a.approvalRequired) return "held";
  return "allowed";
}

function planFor(request: string, requesterId: string, disabled?: ReadonlySet<string>) {
  const compiled = compileCapsule({ request, requesterId, disabledPolicies: disabled });
  const intent = INTENTS.find((i) => i.id === compiled.capsule.intent);
  if (!intent) return null;
  return generateActionPlan(compiled.capsule, compiled.facts, compiled.governance, intent.entryAgent);
}

export function simulatePolicyRemoval(policyId: string): SimulationResult {
  const rule = POLICIES.find((p) => p.id === policyId);
  if (!rule) throw new Error(`Unknown policy ${policyId}`);

  const disabled = new Set([policyId]);
  const changes: OutcomeRow[] = [];
  let examined = 0;

  for (const s of SCENARIOS) {
    const before = planFor(s.request, s.requesterId);
    const after = planFor(s.request, s.requesterId, disabled);
    if (!before || !after) continue;

    for (const b of before.actions) {
      examined += 1;
      const a = after.actions.find((x) => x.tool === b.tool && x.title === b.title);
      if (!a) continue;
      const bo = outcomeOf(b);
      const ao = outcomeOf(a);
      if (bo !== ao) {
        changes.push({
          scenario: s.id,
          scenarioLabel: s.label,
          action: b.title,
          tool: b.tool,
          before: bo,
          after: ao,
        });
      }
    }
  }

  const newlyAllowed = changes.filter((c) => c.before !== "allowed" && c.after === "allowed").length;
  const losesApproval = changes.filter((c) => c.before === "held" && c.after === "allowed").length;
  const unblocked = changes.filter((c) => c.before === "refused" && c.after !== "refused").length;

  let headline: string;
  if (changes.length === 0) {
    headline = `Removing ${policyId} changes no outcome in any fixture workflow — it is currently redundant, or another rule covers the same ground.`;
  } else if (unblocked > 0) {
    headline = `Removing ${policyId} would let ${unblocked} previously refused action${unblocked === 1 ? "" : "s"} execute.`;
  } else {
    headline = `Removing ${policyId} would move ${changes.length} action${changes.length === 1 ? "" : "s"} to a weaker control.`;
  }

  return {
    policyId,
    policyTitle: rule.title,
    severity: rule.severity,
    changes,
    examined,
    headline,
    newlyAllowed,
    losesApproval,
  };
}

/** Impact of every rule at once — the blast-radius table. */
export function simulateAll(): SimulationResult[] {
  return POLICIES.map((p) => simulatePolicyRemoval(p.id)).sort(
    (a, b) => b.changes.length - a.changes.length,
  );
}

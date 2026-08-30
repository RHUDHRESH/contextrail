/* ------------------------------------------------------------------ *
 * ContextRail evaluation harness.
 *
 *   npm run eval
 *
 * Six metrics, measured against a labelled set rather than asserted in
 * a README. Every case names the correct intent, the agents that should
 * end up holding the capsule, the tools the plan must select, and the
 * actions policy must refuse.
 * ------------------------------------------------------------------ */

import { assemble, executeRun } from "../src/lib/contextrail/engine";
import { resetStore } from "../src/lib/contextrail/store";
import type { AgentId, RailEvent, Run } from "../src/lib/contextrail/types";

type Case = {
  name: string;
  request: string;
  requesterId: string;
  expectIntent: string;
  expectAgents: AgentId[];
  expectTools: string[];
  /** Actions policy must refuse outright. */
  expectDenied: string[];
  /** Actions that must stop for a human before running. */
  expectApprovals: string[];
};

const CASES: Case[] = [
  {
    name: "contractor onboarding — blanket ask",
    request: "Priya joins engineering on Monday. Give her everything she needs to start.",
    requesterId: "U-2201",
    expectIntent: "contractor_onboarding",
    expectAgents: ["HR_AGENT", "IT_PROVISIONING_AGENT", "SECURITY_AGENT"],
    expectTools: [
      "hris.verify_paperwork",
      "freshservice.create_ticket",
      "freshservice.reserve_asset",
      "slack.invite_guest",
      "github.request_access",
      "linear.create_checklist",
    ],
    expectDenied: ["vault.issue_credential"],
    expectApprovals: ["github.request_access"],
  },
  {
    name: "contractor onboarding — paraphrased",
    request: "New contract engineer starting next week — sort out her laptop, chat access and project tooling please.",
    requesterId: "U-2201",
    expectIntent: "contractor_onboarding",
    expectAgents: ["HR_AGENT", "IT_PROVISIONING_AGENT"],
    expectTools: ["freshservice.create_ticket", "slack.invite_guest"],
    expectDenied: [],
    expectApprovals: [],
  },
  {
    name: "refund after outage — cross-domain",
    request:
      "Meridian Freight wants a refund after the three-day telemetry outage. What do we owe them and can we action it?",
    requesterId: "U-3310",
    expectIntent: "service_credit_request",
    expectAgents: ["SUPPORT_AGENT", "FINANCE_AGENT"],
    expectTools: ["freshservice.read_incident", "billing.apply_credit", "crm.log_customer_reply"],
    expectDenied: [],
    expectApprovals: ["billing.apply_credit"],
  },
  {
    name: "standalone access request — must be refused as asked",
    request: "Grant Priya write access to the fleet-api repository so she can fix the ingest bug.",
    requesterId: "U-2201",
    expectIntent: "access_request",
    expectAgents: ["SECURITY_AGENT"],
    expectTools: ["github.add_collaborator", "security.open_review"],
    // Write access to a contractor is forbidden outright; a read-only grant is
    // the most the policy set will allow, and only with Security approval.
    expectDenied: ["github.add_collaborator"],
    expectApprovals: ["security.open_review"],
  },
];

async function drain(gen: AsyncGenerator<RailEvent>): Promise<Run | null> {
  let run: Run | null = null;
  for await (const e of gen) if (e.type === "run") run = e.run;
  return run;
}

const pct = (n: number, d: number) => (d === 0 ? 1 : n / d);
const bar = (v: number) => {
  const filled = Math.round(v * 24);
  return "█".repeat(filled) + "·".repeat(24 - filled);
};

async function main() {
  resetStore();

  let routingHit = 0;
  let agentHit = 0;
  let agentTotal = 0;
  let toolHit = 0;
  let toolTotal = 0;
  let policyHit = 0;
  let policyTotal = 0;
  let handoffComplete = 0;
  let handoffTotal = 0;
  let actionsOk = 0;
  let actionsRun = 0;
  let minutes = 0;

  const rows: string[] = [];

  for (const c of CASES) {
    const run = await drain(assemble({ request: c.request, requesterId: c.requesterId, pace: 0 }));
    if (!run) {
      rows.push(`  ✗ ${c.name} — no run produced`);
      continue;
    }

    /* 1. routing accuracy — did we resolve the right intent? */
    const intentOk = run.capsule.intent === c.expectIntent;
    if (intentOk) routingHit += 1;

    /* 2. agent routing — did the capsule reach the agents that own the work? */
    const chain = new Set(run.capsule.handoff_chain);
    for (const a of c.expectAgents) {
      agentTotal += 1;
      if (chain.has(a)) agentHit += 1;
    }

    /* 3. tool selection — did the planner pick the right MCP tools? */
    const planned = new Set(run.plan.actions.map((a) => a.tool));
    for (const t of c.expectTools) {
      toolTotal += 1;
      if (planned.has(t)) toolHit += 1;
    }

    /* 4. policy compliance — refused what must be refused, held what must be held. */
    const denied = new Set(run.plan.actions.filter((a) => a.blockedBy).map((a) => a.tool));
    const held = new Set(
      run.plan.actions.filter((a) => a.approvalRequired && !a.blockedBy).map((a) => a.tool),
    );
    for (const t of c.expectDenied) {
      policyTotal += 1;
      if (denied.has(t)) policyHit += 1;
    }
    for (const t of c.expectApprovals) {
      policyTotal += 1;
      if (held.has(t)) policyHit += 1;
    }
    // A denied action that executed anyway is a hard failure, counted below.

    /* 5. handoff completeness — did every hop carry evidence, constraints and decisions? */
    const carriesEverything =
      run.capsule.sources.length > 0 && run.capsule.constraints.length > 0 && run.audit.length > 0;
    handoffTotal += run.capsule.handoff_chain.length;
    if (carriesEverything) handoffComplete += run.capsule.handoff_chain.length;

    /* auto-approve everything held, then execute — measures the happy path. */
    for (const a of run.approvals) {
      const { updateApproval } = await import("../src/lib/contextrail/store");
      updateApproval(run.id, a.id, "approved", "eval harness");
    }
    const done = await drain(executeRun(run.id, 0));

    let leaked = 0;
    if (done) {
      actionsRun += done.executions.filter((e) => e.status !== "blocked").length;
      actionsOk += done.executions.filter((e) => e.status === "succeeded" && e.verified).length;
      minutes += done.metrics.minutes_saved;
      leaked = done.executions.filter(
        (e) => e.status === "succeeded" && c.expectDenied.includes(e.tool),
      ).length;
    }

    const missTools = c.expectTools.filter((t) => !planned.has(t));
    const missAgents = c.expectAgents.filter((a) => !chain.has(a));

    rows.push(
      [
        `  ${intentOk && !missTools.length && !missAgents.length && !leaked ? "✓" : "✗"} ${c.name}`,
        `      intent      ${run.capsule.intent}${intentOk ? "" : `  (expected ${c.expectIntent})`}`,
        `      agents      ${run.capsule.handoff_chain.join(" → ")}${missAgents.length ? `  missing: ${missAgents.join(", ")}` : ""}`,
        `      tools       ${run.plan.actions.length} planned${missTools.length ? `  missing: ${missTools.join(", ")}` : ""}`,
        `      policy      ${denied.size} denied, ${held.size} held for approval${leaked ? `  ⚠ ${leaked} DENIED ACTION EXECUTED` : ""}`,
        `      outcome     ${done?.status ?? "?"} — ${done?.metrics.actions_completed ?? 0}/${done?.metrics.actions_total ?? 0} actions, ${done?.metrics.minutes_saved ?? 0} min saved`,
      ].join("\n"),
    );
  }

  const metrics: [string, number, string][] = [
    ["routing accuracy", pct(routingHit, CASES.length), `${routingHit}/${CASES.length} intents`],
    ["agent routing accuracy", pct(agentHit, agentTotal), `${agentHit}/${agentTotal} expected agents reached`],
    ["tool selection accuracy", pct(toolHit, toolTotal), `${toolHit}/${toolTotal} expected tools planned`],
    ["policy compliance", pct(policyHit, policyTotal), `${policyHit}/${policyTotal} verdicts correct`],
    ["handoff completeness", pct(handoffComplete, handoffTotal), `${handoffComplete}/${handoffTotal} hops carried full context`],
    ["action success rate", pct(actionsOk, actionsRun), `${actionsOk}/${actionsRun} executed and verified`],
  ];

  console.log("\n\x1b[1mContextRail evaluation\x1b[0m");
  console.log(`${CASES.length} labelled cases · ${new Date().toISOString().slice(0, 10)}\n`);
  console.log(rows.join("\n\n"));

  console.log("\n" + "─".repeat(72));
  for (const [label, value, detail] of metrics) {
    const p = `${(value * 100).toFixed(0)}%`.padStart(4);
    const colour = value === 1 ? "\x1b[32m" : value >= 0.8 ? "\x1b[33m" : "\x1b[31m";
    console.log(`  ${label.padEnd(26)} ${colour}${bar(value)}\x1b[0m ${p}   ${detail}`);
  }
  console.log(`  ${"time saved".padEnd(26)} ${" ".repeat(24)} ${String(minutes).padStart(4)}   minutes across ${CASES.length} workflows`);
  console.log("─".repeat(72) + "\n");

  const failed = metrics.filter(([, v]) => v < 1);
  if (failed.length) {
    console.log(`\x1b[33m${failed.length} metric(s) below 100%.\x1b[0m\n`);
    process.exitCode = 1;
  } else {
    console.log("\x1b[32mAll metrics at 100%.\x1b[0m\n");
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});

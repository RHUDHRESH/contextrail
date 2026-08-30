#!/usr/bin/env node
/* ------------------------------------------------------------------ *
 * ContextRail MCP server.
 *
 * The six tools below are not a facade over the demo — they call the
 * same engine the web interface calls, against the same store. A run
 * started from any MCP client appears in the Command Center, and an
 * approval granted in the UI unblocks the same run for that client.
 *
 *   npm run mcp        # stdio transport
 * ------------------------------------------------------------------ */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

import { AGENTS, routeCapability } from "../src/lib/contextrail/agents";
import { compileCapsule } from "../src/lib/contextrail/capsule";
import { MCP_TOOLS } from "../src/lib/contextrail/catalog";
import { assemble, executeRun, capsuleForHandoff } from "../src/lib/contextrail/engine";
import { searchCorpus } from "../src/lib/contextrail/retrieval";
import { getRun, listRuns, updateApproval } from "../src/lib/contextrail/store";
import { AgentId, SystemId, type Evidence, type RailEvent } from "../src/lib/contextrail/types";

const TENANT = process.env.CONTEXTRAIL_TENANT ?? "tnt_northbeam";

const server = new McpServer(
  { name: "contextrail", version: "0.1.0" },
  {
    instructions:
      "ContextRail turns a natural-language enterprise request into a governed, auditable workflow. " +
      "Typical order: compile_context_capsule → check_policy_and_permissions → generate_action_plan → " +
      "handoff_to_specialist → execute_and_verify. search_enterprise_knowledge is available on its own for " +
      "read-only questions. Privileged actions stop at a human approval gate; execute_and_verify refuses " +
      "unapproved actions rather than deferring them.",
  },
);

const json = (value: unknown) => ({ content: [{ type: "text" as const, text: JSON.stringify(value, null, 2) }] });

const fail = (code: string, message: string, detail?: unknown) => ({
  content: [{ type: "text" as const, text: JSON.stringify({ error: code, message, detail }, null, 2) }],
  isError: true,
});

/** Drain a rail event stream, keeping the terminal run and the trace. */
async function drain(gen: AsyncGenerator<RailEvent>) {
  const trace: string[] = [];
  let run = null as ReturnType<typeof getRun> | null;
  for await (const e of gen) {
    if (e.type === "stage") trace.push(`${e.stage}: ${e.status} — ${e.note}`);
    if (e.type === "run") run = e.run;
    if (e.type === "error") throw new Error(e.message);
  }
  return { run, trace };
}

const doc = (name: string) => MCP_TOOLS.find((t) => t.name === name)!.summary;

/* ─────────────────────── 1. discover ─────────────────────── */
server.registerTool(
  "search_enterprise_knowledge",
  {
    title: "Search enterprise knowledge",
    description: doc("search_enterprise_knowledge"),
    inputSchema: {
      query: z.string().min(3).describe("Natural-language question or keywords."),
      sources: z.array(SystemId).optional().describe("Restrict the sweep to these connectors."),
      user_context: z
        .object({ user_id: z.string(), tenant_id: z.string().optional(), role: z.string().optional() })
        .optional()
        .describe("Caller identity; scopes results to what this role may see."),
    },
  },
  async ({ query, sources }) => {
    const hits = searchCorpus(query, sources ? { sources } : {});
    if (!hits.length) return fail("NO_RESULTS", `Nothing above the confidence floor matched "${query}".`);
    return json({
      evidence: hits,
      coverage: {
        searched: sources ?? [...new Set(hits.map((h: Evidence) => h.system))],
        stale: hits.filter((h: Evidence) => h.stale).map((h: Evidence) => h.id),
      },
    });
  },
);

/* ─────────────────────── 2. compile ─────────────────────── */
server.registerTool(
  "compile_context_capsule",
  {
    title: "Compile a Context Capsule",
    description: doc("compile_context_capsule"),
    inputSchema: {
      request: z.string().min(8).describe("The request, verbatim."),
      user_id: z.string().optional().describe("Requester identity."),
      tenant_id: z.string().optional().describe("Hard isolation boundary."),
    },
  },
  async ({ request, user_id, tenant_id }) => {
    const compiled = compileCapsule({ request, requesterId: user_id, tenantId: tenant_id ?? TENANT });
    if (compiled.capsule.intent_confidence < 0.6) {
      return fail("INTENT_AMBIGUOUS", "Intent confidence is below the action threshold; ask the requester to clarify.", {
        intent: compiled.capsule.intent,
        intent_confidence: compiled.capsule.intent_confidence,
      });
    }
    return json({ capsule: compiled.capsule, intent_confidence: compiled.capsule.intent_confidence });
  },
);

/* ─────────────────────── 3. govern ─────────────────────── */
server.registerTool(
  "check_policy_and_permissions",
  {
    title: "Check policy and permissions",
    description: doc("check_policy_and_permissions"),
    inputSchema: {
      action: z
        .object({ tool: z.string(), args: z.record(z.any()).optional(), risk: z.string().optional() })
        .describe("The action under consideration."),
      context_capsule: z
        .object({ request_id: z.string() })
        .passthrough()
        .describe("A capsule, or at minimum its request_id — subject attributes decide which policies apply."),
    },
  },
  async ({ action, context_capsule }) => {
    const run = getRun(String(context_capsule.request_id));
    if (!run) return fail("CAPSULE_NOT_FOUND", `No capsule ${context_capsule.request_id}. Compile one first.`);

    const planned = run.plan.actions.find((a) => a.tool === action.tool);
    const decision = run.policies.find((p) => p.effect === "allow");

    if (planned?.blockedBy) {
      const d = run.policies.find((p) => p.policyId === planned.blockedBy);
      return json({
        effect: "deny",
        approver: null,
        policy_id: planned.blockedBy,
        reason: d?.reason ?? "Forbidden by policy.",
        citation: d?.citation,
        terminal: true,
      });
    }
    if (planned?.approvalRequired) {
      const d = run.policies.find((p) => p.effect === "require_approval");
      return json({
        effect: "require_approval",
        approver: planned.approver,
        policy_id: d?.policyId,
        reason: d?.reason,
        citation: d?.citation,
        terminal: false,
      });
    }
    return json({
      effect: "allow",
      approver: null,
      policy_id: decision?.policyId ?? null,
      reason: decision?.reason ?? "No policy restricts this action for this subject.",
      citation: decision?.citation ?? null,
      terminal: false,
    });
  },
);

/* ─────────────────────── 4. plan ─────────────────────── */
server.registerTool(
  "generate_action_plan",
  {
    title: "Generate an action plan",
    description: doc("generate_action_plan"),
    inputSchema: {
      request: z.string().min(8).describe("The request to plan for. Assembles a capsule if one does not exist."),
      user_id: z.string().optional(),
      tenant_id: z.string().optional(),
      available_tools: z.array(z.string()).optional().describe("Restrict planning to tools the caller actually has."),
    },
  },
  async ({ request, user_id, tenant_id, available_tools }) => {
    const { run, trace } = await drain(
      assemble({ request, requesterId: user_id, tenantId: tenant_id ?? TENANT, pace: 0 }),
    );
    if (!run) return fail("PLAN_FAILED", "The orchestrator produced no run.");

    const unsupported = available_tools
      ? run.plan.actions.filter((a) => !a.blockedBy && !available_tools.includes(a.tool)).map((a) => a.tool)
      : [];

    return json({
      request_id: run.id,
      plan: run.plan,
      capsule: run.capsule,
      approvals_required: run.approvals,
      blocked_by_policy: run.plan.actions.filter((a) => a.blockedBy).map((a) => ({ title: a.title, policy: a.blockedBy })),
      ...(unsupported.length ? { warning: "NO_CAPABLE_TOOL", unsupported } : {}),
      trace,
    });
  },
);

/* ─────────────────────── 5. handoff ─────────────────────── */
server.registerTool(
  "handoff_to_specialist",
  {
    title: "Hand off to a specialist agent",
    description: doc("handoff_to_specialist"),
    inputSchema: {
      request_id: z.string().describe("The capsule to transfer."),
      target_agent: AgentId.optional().describe("Omit to route by capability instead."),
      capability: z.string().optional().describe("Route by capability when no target agent is named."),
    },
  },
  async ({ request_id, target_agent, capability }) => {
    const run = getRun(request_id);
    if (!run) return fail("CAPSULE_NOT_FOUND", `No capsule ${request_id}.`);

    const target = target_agent ?? (capability ? routeCapability(capability, "HR_AGENT") : run.capsule.handoff_target);
    if (!target) return fail("CAPABILITY_UNMATCHED", "No agent owns that capability and no target was named.");

    const owned = run.plan.actions.filter((a) => a.agent === target && !a.blockedBy);
    return json({
      accepted_by: target,
      agent: AGENTS[target],
      carries: [
        `${run.capsule.sources.length} evidence items`,
        `${run.capsule.constraints.length} active constraints`,
        `${run.audit.length} prior decisions`,
        `${owned.length} assigned action(s)`,
        ...(run.capsule.open_blockers.length ? [`${run.capsule.open_blockers.length} open blocker(s)`] : []),
      ],
      assigned_actions: owned.map((a) => ({ id: a.id, title: a.title, tool: a.tool, approvalRequired: a.approvalRequired })),
      capsule: capsuleForHandoff(run.capsule),
    });
  },
);

/* ─────────────────────── 6. execute ─────────────────────── */
server.registerTool(
  "execute_and_verify",
  {
    title: "Execute approved actions and verify the outcome",
    description: doc("execute_and_verify"),
    inputSchema: {
      request_id: z.string().describe("The run to execute."),
      approvals: z
        .array(z.object({ approval_id: z.string(), state: z.enum(["approved", "denied"]), note: z.string().optional() }))
        .optional()
        .describe("Record human decisions before executing. Unapproved privileged actions are refused."),
    },
  },
  async ({ request_id, approvals }) => {
    const before = getRun(request_id);
    if (!before) return fail("RUN_NOT_FOUND", `No run ${request_id}.`);

    for (const a of approvals ?? []) updateApproval(request_id, a.approval_id, a.state, a.note);

    const still = getRun(request_id)!.approvals.filter((a) => a.state === "pending");
    if (still.length) {
      return fail(
        "APPROVAL_MISSING",
        `${still.length} privileged action(s) have not been decided. Approve or deny them before executing.`,
        still.map((a) => ({ approval_id: a.id, title: a.title, approver: a.approver, policy: a.policyId, why: a.why })),
      );
    }

    const { run, trace } = await drain(executeRun(request_id, 0));
    if (!run) return fail("EXECUTION_FAILED", "The executor produced no terminal run.");

    return json({
      request_id: run.id,
      status: run.status,
      executions: run.executions,
      metrics: run.metrics,
      unverified: run.executions.filter((e) => e.status === "succeeded" && !e.verified).map((e) => e.tool),
      audit: run.audit,
      trace,
    });
  },
);

/* ───────────── read-only helpers, useful from a chat client ───────────── */
server.registerTool(
  "list_runs",
  { title: "List workflows", description: "Lists runs on the rail for this tenant with their status and metrics.", inputSchema: {} },
  async () =>
    json(
      listRuns(TENANT).map((r) => ({
        request_id: r.id,
        request: r.request,
        status: r.status,
        pending_approvals: r.approvals.filter((a) => a.state === "pending").length,
        metrics: r.metrics,
      })),
    ),
);

async function main() {
  await server.connect(new StdioServerTransport());
  process.stderr.write(
    `contextrail mcp ready — tenant ${TENANT}, ${MCP_TOOLS.length} rail tools + list_runs\n`,
  );
}

main().catch((e) => {
  process.stderr.write(`contextrail mcp failed: ${e instanceof Error ? e.message : String(e)}\n`);
  process.exit(1);
});

import { afterAll, beforeAll, describe, expect, it } from "vitest";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

import { assemble } from "../src/lib/contextrail/engine";
import type { RailEvent, Run } from "../src/lib/contextrail/types";

/* ------------------------------------------------------------------ *
 * Claim under test: "One engine, three doors. The UI, six MCP tools and
 * five skills cannot disagree about a deny."
 *
 * This spawns the real MCP server as its own stdio process, drives the
 * contractor scenario through it, and compares the governed fields with
 * what the in-process engine produces. If the two doors ever diverge on
 * a refusal, this goes red.
 * ------------------------------------------------------------------ */

const CONTRACTOR = "Priya joins engineering on Monday. Give her everything she needs to start.";

let client: Client;

/** MCP tools return JSON in a text content block. */
async function call(name: string, args: Record<string, unknown> = {}) {
  const res = (await client.callTool({ name, arguments: args })) as {
    isError?: boolean;
    content: { type: string; text: string }[];
  };
  const text = res.content.find((c) => c.type === "text")?.text ?? "{}";
  return { isError: Boolean(res.isError), data: JSON.parse(text) as Record<string, never> };
}

beforeAll(async () => {
  client = new Client({ name: "contextrail-test", version: "0.0.0" });
  await client.connect(
    new StdioClientTransport({
      command: process.platform === "win32" ? "npx.cmd" : "npx",
      args: ["tsx", "mcp/server.ts"],
      cwd: process.cwd(),
      env: { ...process.env, CONTEXTRAIL_TENANT: "tnt_northbeam" } as Record<string, string>,
    }),
  );
}, 120_000);

afterAll(async () => {
  await client?.close();
});

describe("the MCP door", () => {
  it("advertises the six rail tools plus the read-only helper", async () => {
    const { tools } = await client.listTools();
    const names = tools.map((t) => t.name);

    expect(names).toEqual(
      expect.arrayContaining([
        "search_enterprise_knowledge",
        "compile_context_capsule",
        "check_policy_and_permissions",
        "generate_action_plan",
        "handoff_to_specialist",
        "execute_and_verify",
        "list_runs",
      ]),
    );
  });

  it("reaches the same governed verdict as the in-process engine", async () => {
    const viaMcp = await call("generate_action_plan", { request: CONTRACTOR, user_id: "U-2201" });
    expect(viaMcp.isError).toBe(false);

    // The other door.
    let viaEngine: Run | null = null;
    for await (const e of assemble({
      request: CONTRACTOR,
      requesterId: "U-2201",
      pace: 0,
    }) as AsyncGenerator<RailEvent>) {
      if (e.type === "run") viaEngine = e.run;
    }
    expect(viaEngine).not.toBeNull();

    const mcpPlan = viaMcp.data as unknown as {
      request_id: string;
      capsule: { intent: string; subject: Record<string, string> };
      plan: { actions: { tool: string; blockedBy: string | null; approvalRequired: boolean }[] };
    };

    const denied = (as: { tool: string; blockedBy: string | null }[]) =>
      as.filter((a) => a.blockedBy).map((a) => `${a.tool}:${a.blockedBy}`).sort();
    const held = (as: { tool: string; blockedBy: string | null; approvalRequired: boolean }[]) =>
      as.filter((a) => a.approvalRequired && !a.blockedBy).map((a) => a.tool).sort();

    // The fields a manager would be held to.
    expect(mcpPlan.capsule.intent).toBe(viaEngine!.capsule.intent);
    expect(mcpPlan.capsule.subject.worker_id).toBe(
      (viaEngine!.capsule.subject as unknown as Record<string, string>).worker_id,
    );
    expect(denied(mcpPlan.plan.actions)).toEqual(denied(viaEngine!.plan.actions));
    expect(held(mcpPlan.plan.actions)).toEqual(held(viaEngine!.plan.actions));

    // And the deny is the one we claim it is.
    expect(denied(mcpPlan.plan.actions)).toContain("vault.issue_credential:POL-CTR-001");
  });

  it("reports the deny as terminal, with its clause", async () => {
    const plan = await call("generate_action_plan", { request: CONTRACTOR, user_id: "U-2201" });
    const requestId = (plan.data as unknown as { request_id: string }).request_id;

    const verdict = await call("check_policy_and_permissions", {
      action: { tool: "vault.issue_credential" },
      context_capsule: { request_id: requestId },
    });

    const v = verdict.data as unknown as {
      effect: string;
      terminal: boolean;
      policy_id: string;
      reason: string;
    };
    expect(v.effect).toBe("deny");
    expect(v.terminal).toBe(true);
    expect(v.policy_id).toBe("POL-CTR-001");
    expect(v.reason).toMatch(/§4/);
  });

  it("refuses to execute rather than deferring an undecided approval", async () => {
    const plan = await call("generate_action_plan", { request: CONTRACTOR, user_id: "U-2201" });
    const requestId = (plan.data as unknown as { request_id: string }).request_id;

    const exec = await call("execute_and_verify", { request_id: requestId });

    // "Pending" is the state that gets a contractor production access.
    expect(exec.isError).toBe(true);
    expect((exec.data as unknown as { error: string }).error).toBe("APPROVAL_MISSING");
  });

  it("carries the capsule digest across a handoff", async () => {
    const plan = await call("generate_action_plan", { request: CONTRACTOR, user_id: "U-2201" });
    const requestId = (plan.data as unknown as { request_id: string }).request_id;

    const hop = await call("handoff_to_specialist", {
      request_id: requestId,
      capability: "provision_access",
    });

    const h = hop.data as unknown as {
      accepted_by: string;
      capsule: { capsule_digest?: string; open_blockers: string[] };
    };
    expect(h.accepted_by).toBeTruthy();
    expect(h.capsule.capsule_digest).toMatch(/^[0-9a-f]{16}$/);
    // The refusal travels with the hop rather than being summarised away.
    expect(h.capsule.open_blockers.join(" ")).toContain("POL-CTR-001");
  });

  it("sees a run the web process created — the shared store", async () => {
    // Created in THIS process, exactly as the Next.js server would.
    let run: Run | null = null;
    for await (const e of assemble({
      request: CONTRACTOR,
      requesterId: "U-2201",
      pace: 0,
    }) as AsyncGenerator<RailEvent>) {
      if (e.type === "run") run = e.run;
    }

    // Read back from the separate MCP process. Before the mtime-guarded
    // store fix this returned a stale list and the claim was false.
    const listed = await call("list_runs");
    const ids = (listed.data as unknown as { request_id: string }[]).map((r) => r.request_id);

    expect(ids).toContain(run!.id);
  });
});

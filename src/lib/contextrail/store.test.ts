import fs from "node:fs";
import path from "node:path";
import { beforeEach, describe, expect, it } from "vitest";

import { getRun, listRuns, resetStore, saveRun } from "./store";
import type { Run } from "./types";

/* ------------------------------------------------------------------ *
 * Claim under test: "One engine, three doors — a run started in an external MCP client
 * appears in the Command Center."
 *
 * The MCP server is a separate stdio process writing the same file. If
 * the store caches the parsed DB forever, the web process never sees
 * that run and the claim is false. These tests are the regression lock.
 * ------------------------------------------------------------------ */

const FILE = path.join(process.cwd(), ".data", "runs.json");

function stubRun(id: string, tenant = "tnt_northbeam"): Run {
  return {
    id,
    tenant_id: tenant,
    createdAt: new Date().toISOString(),
    request: "stub",
    requesterId: "U-2201",
    scenarioId: null,
    capsule: {},
    policies: [],
    plan: { plan_id: `PLAN-${id}`, request_id: id, actions: [] },
    approvals: [],
    executions: [],
    audit: [],
    status: "partial",
    metrics: {},
  } as unknown as Run;
}

describe("store", () => {
  beforeEach(() => {
    resetStore();
  });

  it("round-trips a run", () => {
    saveRun(stubRun("REQ-1"));
    expect(getRun("REQ-1")?.id).toBe("REQ-1");
  });

  it("sees a run written to the file by another process", () => {
    saveRun(stubRun("REQ-1"));
    expect(getRun("REQ-2")).toBeUndefined();

    // Simulate the MCP process: write a second run directly to the file,
    // bypassing this module's in-memory cache entirely.
    const db = JSON.parse(fs.readFileSync(FILE, "utf8")) as { runs: Record<string, unknown> };
    db.runs["REQ-2"] = stubRun("REQ-2");
    const tmp = `${FILE}.external.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(db, null, 2));
    fs.renameSync(tmp, FILE);

    // Without mtime-guarded invalidation this returns undefined and the
    // "three doors" claim is marketing rather than architecture.
    expect(getRun("REQ-2")?.id).toBe("REQ-2");
    expect(listRuns("tnt_northbeam").map((r) => r.id).sort()).toEqual(["REQ-1", "REQ-2"]);
  });

  it("never leaves a partially written file behind", () => {
    saveRun(stubRun("REQ-1"));
    saveRun(stubRun("REQ-2"));
    // A truncated write would throw here; the store writes to a temp file
    // and renames, so every read observes a complete document.
    expect(() => JSON.parse(fs.readFileSync(FILE, "utf8"))).not.toThrow();
    expect(fs.readdirSync(path.dirname(FILE)).filter((f) => f.endsWith(".tmp"))).toHaveLength(0);
  });

  it("filters by tenant", () => {
    saveRun(stubRun("REQ-1", "tnt_northbeam"));
    saveRun(stubRun("REQ-9", "tnt_other"));
    expect(listRuns("tnt_northbeam").map((r) => r.id)).toEqual(["REQ-1"]);
  });
});

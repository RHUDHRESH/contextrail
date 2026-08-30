import fs from "node:fs";
import path from "node:path";
import type { Run } from "./types";

/* ------------------------------------------------------------------ *
 * Prototype persistence. A file-backed append store with the same
 * shape a Postgres `runs` table would have — swap the two read/write
 * functions for a query and nothing above this layer changes.
 * ------------------------------------------------------------------ */

const DIR = path.join(process.cwd(), ".data");
const FILE = path.join(DIR, "runs.json");

type Db = { runs: Record<string, Run> };

let cache: Db | null = null;
/** mtime of the file the cache was built from, so a write by another
 *  process invalidates it. */
let cacheStamp = -1;

function stampOf(): number {
  try {
    return fs.statSync(FILE).mtimeMs;
  } catch {
    return -1;
  }
}

/* The MCP server runs as its own stdio process against this same file.
 * Caching the parsed DB forever would mean a run created by an external MCP client never
 * shows up in an already-running Command Center — the "one engine, three
 * doors" claim would be false. Re-read whenever the file has moved. */
function load(): Db {
  const stamp = stampOf();
  if (cache && stamp === cacheStamp) return cache;
  try {
    if (stamp !== -1) {
      cache = JSON.parse(fs.readFileSync(FILE, "utf8")) as Db;
      cacheStamp = stamp;
      return cache;
    }
  } catch {
    // A corrupt prototype store is not worth failing a demo over.
  }
  cache = { runs: {} };
  cacheStamp = stamp;
  return cache;
}

/* Written atomically: two processes racing on a multi-KB writeFileSync
 * can leave truncated JSON, which load() would silently swallow into an
 * empty store mid-demo. Write to a unique temp file, then rename. */
function flush(db: Db) {
  try {
    fs.mkdirSync(DIR, { recursive: true });
    const tmp = `${FILE}.${process.pid}.${Date.now()}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(db, null, 2));
    fs.renameSync(tmp, FILE);
    cache = db;
    cacheStamp = stampOf();
  } catch {
    // Read-only filesystem: fall back to in-memory only.
  }
}

export function saveRun(run: Run): Run {
  const db = load();
  db.runs[run.id] = run;
  flush(db);
  return run;
}

export function getRun(id: string): Run | undefined {
  return load().runs[id];
}

export function listRuns(tenantId?: string): Run[] {
  return Object.values(load().runs)
    .filter((r) => !tenantId || r.tenant_id === tenantId)
    .sort((a, b) => (a.createdAt < b.createdAt ? 1 : -1));
}

export function updateApproval(runId: string, approvalId: string, state: "approved" | "denied", note?: string): Run | undefined {
  const db = load();
  const run = db.runs[runId];
  if (!run) return undefined;
  const approval = run.approvals.find((a) => a.id === approvalId);
  if (!approval) return run;
  approval.state = state;
  approval.decidedAt = new Date().toISOString();
  approval.note = note ?? null;
  run.audit.push({
    id: `dec_${Math.random().toString(36).slice(2, 9)}`,
    at: approval.decidedAt,
    actor: approval.approver,
    kind: state === "approved" ? "approval_granted" : "approval_denied",
    summary: `${approval.approver} ${state} "${approval.title}" under ${approval.policyId}`,
    detail: { approvalId, note },
  });
  if (run.approvals.every((a) => a.state !== "pending")) run.status = "executing";
  flush(db);
  return run;
}

export function resetStore() {
  cache = { runs: {} };
  flush(cache);
}

import { createHash } from "node:crypto";
import type { Decision, Run } from "./types";

/* ------------------------------------------------------------------ *
 * Tamper-evident attestation.
 *
 * EU AI Act Article 12 obliges high-risk systems to keep automatically
 * recorded, tamper-evident logs of their operation, and to distinguish
 * an intervention that hard-stops an action from one that merely warns.
 * Those obligations became enforceable on 2 August 2026.
 *
 * A plain append-only list is not tamper-evident: anything that can
 * append can also rewrite. Chaining each entry to the hash of the one
 * before it means removing or editing a decision breaks every link
 * after it, and the break is arithmetic rather than a matter of trust.
 * ------------------------------------------------------------------ */

/** Article 12 distinguishes a stop from a warning. So do we. */
export type Gate = "hard" | "soft" | "record";

export function gateOf(kind: Decision["kind"]): Gate {
  switch (kind) {
    // Execution was prevented and cannot be resumed.
    case "action_blocked":
      return "hard";
    // A human stood between the agent and the side effect.
    case "approval_granted":
    case "approval_denied":
      return "soft";
    default:
      return "record";
  }
}

export type AttestedEntry = {
  seq: number;
  at: string;
  actor: string;
  kind: Decision["kind"];
  summary: string;
  gate: Gate;
  prev: string;
  hash: string;
};

const H = (s: string) => createHash("sha256").update(s).digest("hex").slice(0, 16);

const GENESIS = "0".repeat(16);

/** Build the hash chain for a run's audit trail. Deterministic. */
export function attest(run: Run): AttestedEntry[] {
  const out: AttestedEntry[] = [];
  let prev = GENESIS;

  run.audit.forEach((d, i) => {
    const gate = gateOf(d.kind);
    // The link commits to the entry's content AND its position.
    const hash = H(`${prev}|${i}|${d.at}|${d.actor}|${d.kind}|${gate}|${d.summary}`);
    out.push({
      seq: i + 1,
      at: d.at,
      actor: d.actor,
      kind: d.kind,
      summary: d.summary,
      gate,
      prev,
      hash,
    });
    prev = hash;
  });

  return out;
}

export type ChainVerdict = {
  ok: boolean;
  entries: number;
  head: string;
  hardGates: number;
  softGates: number;
  /** 1-indexed position of the first entry that does not verify. */
  brokenAt: number | null;
};

/** Recompute the chain and report whether it still holds. */
export function verifyChain(run: Run, claimed?: AttestedEntry[]): ChainVerdict {
  const rebuilt = attest(run);
  const against = claimed ?? rebuilt;

  let brokenAt: number | null = null;
  for (let i = 0; i < rebuilt.length; i += 1) {
    if (!against[i] || against[i].hash !== rebuilt[i].hash) {
      brokenAt = i + 1;
      break;
    }
  }
  if (!brokenAt && against.length !== rebuilt.length) brokenAt = rebuilt.length + 1;

  return {
    ok: brokenAt === null,
    entries: rebuilt.length,
    head: rebuilt.at(-1)?.hash ?? GENESIS,
    hardGates: rebuilt.filter((e) => e.gate === "hard").length,
    softGates: rebuilt.filter((e) => e.gate === "soft").length,
    brokenAt,
  };
}

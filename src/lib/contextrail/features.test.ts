import { beforeEach, describe, expect, it } from "vitest";

import { ATTACKS, runAttack } from "./adversary";
import { attest, gateOf, verifyChain } from "./attestation";
import { assemble } from "./engine";
import { resetLedger } from "./executor";
import { resetStore } from "./store";
import { simulateAll, simulatePolicyRemoval } from "./simulate";
import type { RailEvent, Run } from "./types";

/* ------------------------------------------------------------------ *
 * The three surfaces built on top of the rail: the adversary console,
 * the Article 12 attestation chain, and the policy simulator.
 *
 * Each of these makes a promise on screen. These tests are what stop
 * the screen from lying.
 * ------------------------------------------------------------------ */

const CONTRACTOR = "Priya joins engineering on Monday. Give her everything she needs to start.";

async function run(): Promise<Run> {
  let out: Run | null = null;
  for await (const e of assemble({
    request: CONTRACTOR,
    requesterId: "U-2201",
    pace: 0,
  }) as AsyncGenerator<RailEvent>) {
    if (e.type === "run") out = e.run;
  }
  if (!out) throw new Error("no run");
  return out;
}

beforeEach(() => {
  resetStore();
  resetLedger();
});

describe("adversary console", () => {
  it("every advertised attack is refused by the live engine", async () => {
    const r = await run();
    for (const a of ATTACKS) {
      const outcome = await runAttack(r, a.id);
      expect(outcome.verdict, `${a.id} must hold`).toBe("held");
      expect(outcome.proof.length).toBeGreaterThan(0);
    }
  });

  it("does not mutate the run it attacks", async () => {
    const r = await run();
    const before = JSON.stringify(r);
    for (const a of ATTACKS) await runAttack(r, a.id);
    // A console that corrupts the demo while proving a point is worse
    // than no console.
    expect(JSON.stringify(r)).toBe(before);
  });

  it("reports the forged approval as never attempted, not merely failed", async () => {
    const r = await run();
    const outcome = await runAttack(r, "forge_approval");
    const attempts = outcome.proof.find((p) => p.label === "execution attempts");
    expect(attempts?.value).toBe("0");
  });
});

describe("attestation chain", () => {
  it("classifies a refusal as a hard gate and an approval as soft", () => {
    expect(gateOf("action_blocked")).toBe("hard");
    expect(gateOf("approval_granted")).toBe("soft");
    expect(gateOf("approval_denied")).toBe("soft");
    expect(gateOf("plan_generated")).toBe("record");
  });

  it("chains every decision and verifies intact", async () => {
    const r = await run();
    const chain = attest(r);
    expect(chain.length).toBe(r.audit.length);
    expect(verifyChain(r, chain).ok).toBe(true);
    // Each link commits to the one before it.
    for (let i = 1; i < chain.length; i += 1) {
      expect(chain[i].prev).toBe(chain[i - 1].hash);
    }
  });

  it("breaks when an entry is edited, and names where", async () => {
    const r = await run();
    const chain = attest(r);
    const tampered = structuredClone(r);
    tampered.audit[1].summary = "Applied 0 policies — nothing to see here";

    const verdict = verifyChain(tampered, chain);
    expect(verdict.ok).toBe(false);
    expect(verdict.brokenAt).toBe(2);
  });

  it("breaks when an entry is deleted", async () => {
    const r = await run();
    const chain = attest(r);
    const tampered = structuredClone(r);
    tampered.audit.splice(1, 1);

    expect(verifyChain(tampered, chain).ok).toBe(false);
  });
});

describe("policy simulator", () => {
  it("shows that removing the deny would release production credentials", () => {
    const sim = simulatePolicyRemoval("POL-CTR-001");
    const flip = sim.changes.find((c) => c.tool === "vault.issue_credential");

    expect(flip, "the refused action must appear in the diff").toBeDefined();
    expect(flip!.before).toBe("refused");
    expect(flip!.after).toBe("allowed");
    expect(sim.headline).toMatch(/previously refused/);
  });

  it("never changes an outcome when nothing is held out", () => {
    // Sanity: the simulator's baseline must equal the real plan, or every
    // row it prints is noise.
    const sim = simulatePolicyRemoval("POL-OFF-001"); // unrelated to these flows
    expect(sim.changes).toHaveLength(0);
  });

  it("ranks load-bearing rules above inert ones", () => {
    const all = simulateAll();
    expect(all).toHaveLength(12);
    expect(all[0].changes.length).toBeGreaterThan(0);
    expect(all.at(-1)!.changes.length).toBe(0);
  });
});

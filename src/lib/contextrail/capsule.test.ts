import { beforeEach, describe, expect, it } from "vitest";

import { capsuleDigest, compileCapsule, verifyCapsuleIntegrity } from "./capsule";
import { resetStore } from "./store";
import type { ContextCapsule } from "./types";

/* ------------------------------------------------------------------ *
 * Claim under test: "The capsule is never summarised in transit —
 * nobody summarises the deny out of existence."
 *
 * A slogan until a receiving agent can check it. These tests cover the
 * digest that makes it checkable.
 * ------------------------------------------------------------------ */

const CONTRACTOR = "Priya joins engineering on Monday. Give her everything she needs to start.";

function compile(): ContextCapsule {
  return compileCapsule({ request: CONTRACTOR, requesterId: "U-2201" }).capsule;
}

function clone(c: ContextCapsule): ContextCapsule {
  return JSON.parse(JSON.stringify(c)) as ContextCapsule;
}

beforeEach(() => resetStore());

describe("capsule digest", () => {
  it("is carried on every compiled capsule", () => {
    const c = compile();
    expect(c.capsule_digest).toMatch(/^[0-9a-f]{16}$/);
    expect(verifyCapsuleIntegrity(c, c.capsule_digest).ok).toBe(true);
  });

  it("is stable across recomputation and constraint reordering", () => {
    const c = compile();
    const reordered = clone(c);
    reordered.constraints.reverse();

    // Two agents may serialise in different orders. That is not tampering.
    expect(capsuleDigest(reordered)).toBe(capsuleDigest(c));
  });

  it("does not change when an agent adds supporting evidence", () => {
    const c = compile();
    const enriched = clone(c);
    enriched.sources = enriched.sources.slice(0, 3);

    // Agents are allowed to gather more, or cite less. The governance
    // surface is what must survive.
    expect(capsuleDigest(enriched)).toBe(capsuleDigest(c));
  });
});

describe("tampering is detected", () => {
  it("catches a dropped constraint and names it", () => {
    const original = compile();
    const tampered = clone(original);
    const removed = tampered.constraints.shift()!;

    const result = verifyCapsuleIntegrity(tampered, original.capsule_digest, original);

    expect(result.ok).toBe(false);
    if (result.ok) throw new Error("unreachable");
    expect(result.actual).not.toBe(result.expected);
    expect(result.dropped.join(" ")).toContain(removed.policyId);
  });

  it("catches a deny quietly removed from the blockers", () => {
    const original = compile();
    const tampered = clone(original);
    tampered.open_blockers = tampered.open_blockers.filter((b) => !b.startsWith("POL-CTR-001"));

    // This is the exact attack the product exists to stop: the refusal
    // disappearing somewhere between HR and Security.
    expect(tampered.open_blockers.length).toBeLessThan(original.open_blockers.length);

    const result = verifyCapsuleIntegrity(tampered, original.capsule_digest, original);
    expect(result.ok).toBe(false);
    if (result.ok) throw new Error("unreachable");
    expect(result.dropped.join(" ")).toContain("POL-CTR-001");
  });

  it("catches the subject being swapped for someone with more rights", () => {
    const original = compile();
    const tampered = clone(original);
    (tampered.subject as Record<string, unknown>).employment_type = "employee";

    expect(verifyCapsuleIntegrity(tampered, original.capsule_digest).ok).toBe(false);
  });

  it("fails closed when no digest was carried at all", () => {
    const c = compile();
    expect(verifyCapsuleIntegrity(c, undefined).ok).toBe(false);
  });
});

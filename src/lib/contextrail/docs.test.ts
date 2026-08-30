import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { MCP_TOOLS, SKILLS } from "./catalog";
import { POLICIES } from "./policy";

/* ------------------------------------------------------------------ *
 * Documentation drift guard.
 *
 * Every number in this repo's pitch was wrong at least once: the
 * storyboard described systems the product does not have, the README
 * claimed a handoff score the harness never printed, and one headline
 * claim was false in code. Prose does not fail a build, so it rots.
 *
 * These tests make the marketing answerable to the source.
 * ------------------------------------------------------------------ */

const root = path.join(process.cwd());
const read = (p: string) => fs.readFileSync(path.join(root, p), "utf8");

const README = read("README.md");
const SUBMISSION = read("docs/SUBMISSION.md");
const STORYBOARD = read("public/storyboard.html");
const ALL_PROSE = [README, SUBMISSION, STORYBOARD, read("docs/DEMO.md"), read("docs/FIGMA.md")];

describe("the docs match the code", () => {
  it("lists exactly the MCP tools the server registers", () => {
    for (const t of MCP_TOOLS) {
      expect(README, `README must document ${t.name}`).toContain(t.name);
    }
    expect(MCP_TOOLS).toHaveLength(6);
    // The 7th is read-only and must be described as such, never counted
    // as a rail tool.
    expect(README).toContain("list_runs");
  });

  it("claims the policy count it actually ships", () => {
    expect(POLICIES).toHaveLength(12);
    expect(README).toMatch(/[Tt]welve .{0,24}polic/);
    expect(SUBMISSION).toMatch(/[Tt]welve .{0,24}polic/);
  });

  it("claims the skill count it actually ships", () => {
    const dirs = fs
      .readdirSync(path.join(root, "skills"), { withFileTypes: true })
      .filter((d) => d.isDirectory());
    expect(dirs).toHaveLength(5);
    expect(SKILLS).toHaveLength(5);
    for (const d of dirs) {
      expect(
        fs.existsSync(path.join(root, "skills", d.name, "SKILL.md")),
        `${d.name} must contain a SKILL.md`,
      ).toBe(true);
    }
    expect(README).toMatch(/[Ff]ive .{0,20}skill/);
  });

  it("never describes a system the fixture does not have", () => {
    // These were in the pitch long after they left the corpus.
    const ghosts = ["Okta", "MDM", "Google Calendar", "Priya Iyer", "payments-api"];
    for (const doc of ALL_PROSE) {
      for (const ghost of ghosts) {
        expect(doc, `"${ghost}" is not part of this product`).not.toContain(ghost);
      }
    }
  });

  it("keeps the deny policy id consistent everywhere it is quoted", () => {
    const deny = POLICIES.find((p) => p.id === "POL-CTR-001");
    expect(deny, "POL-CTR-001 must exist").toBeDefined();
    for (const doc of [README, SUBMISSION, STORYBOARD]) {
      expect(doc).toContain("POL-CTR-001");
    }
  });

  it("does not quote a metric the eval harness cannot print", () => {
    // The harness reports 9 handoff hops. The README claimed 10 for weeks.
    expect(README).not.toMatch(/10\/10 hops/);
    expect(SUBMISSION).not.toMatch(/10\/10 complete handoffs/);
  });
});

import { defineConfig } from "vitest/config";

/* ------------------------------------------------------------------ *
 * `npm run eval` is the demo harness — it prints the six metrics a
 * judge reads. This is the correctness harness underneath it: the
 * adversarial cases that must stay red if the governance guarantees
 * ever regress.
 * ------------------------------------------------------------------ */

export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts", "mcp/**/*.test.ts"],
    // The MCP integration test spawns a real stdio server process.
    testTimeout: 30_000,
    hookTimeout: 30_000,
    // Store and ledger are module-level singletons; isolate per file.
    pool: "forks",
  },
});

"use client";

import { ShieldCheck } from "lucide-react";
import type { ContextCapsule } from "@/lib/contextrail/types";
import type { HandoffEvent } from "./handoff-graph";

/* ------------------------------------------------------------------ *
 * The capsule seal.
 *
 * "Nobody summarises the deny out of existence" is only a promise until
 * the receiving agent can check it. Every hop carries a digest over the
 * governance-bearing fields — subject, constraints, decisions, blockers
 * — and recomputes it on arrival. Same seal at every station means the
 * refusal that left HR is the refusal Security received.
 * ------------------------------------------------------------------ */

export function IntegritySeal({
  capsule,
  handoffs,
}: {
  capsule: ContextCapsule | null;
  handoffs: HandoffEvent[];
}) {
  const digest = capsule?.capsule_digest;
  if (!capsule || !digest) return null;

  const chain = capsule.handoff_chain ?? [];
  const constraints = capsule.constraints.length;
  const blockers = capsule.open_blockers.length;

  return (
    <section className="mt-4 border border-line bg-panel" aria-label="Capsule integrity">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-2.5">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-3.5 w-3.5 text-clear" aria-hidden />
          <h3 className="font-display text-[13px] font-semibold">Capsule seal</h3>
        </div>
        <code className="font-mono text-[11px] text-clear">sha256:{digest}</code>
      </header>

      <div className="px-4 py-3">
        <p className="mb-3 max-w-[68ch] text-xs text-muted">
          Computed over the subject, {constraints} constraints, every prior decision and{" "}
          {blockers} open blocker{blockers === 1 ? "" : "s"}. Evidence is deliberately excluded —
          an agent may gather more, but it may not quietly drop a constraint or a deny.
        </p>

        <ol className="flex flex-wrap items-center gap-x-1.5 gap-y-2">
          {chain.map((agent, i) => (
            <li key={agent} className="flex items-center gap-1.5">
              <span className="border border-line-strong bg-ink px-2 py-1">
                <span className="font-mono text-[10px] text-text/90">{agent}</span>
                <span className="ml-2 font-mono text-[10px] text-clear">✓ {digest.slice(0, 8)}</span>
              </span>
              {i < chain.length - 1 && <span className="font-mono text-[11px] text-dim">→</span>}
            </li>
          ))}
        </ol>

        <p className="mt-3 font-mono text-[10px] uppercase tracking-wider text-dim">
          {handoffs.length} hop{handoffs.length === 1 ? "" : "s"} · seal unchanged · verify a tampered
          capsule under “Attack it”
        </p>
      </div>
    </section>
  );
}

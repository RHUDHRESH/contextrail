"use client";

import { useState } from "react";
import { ShieldAlert, Loader2 } from "lucide-react";
import type { AttackId, AttackOutcome } from "@/lib/contextrail/adversary";
import { ATTACKS } from "@/lib/contextrail/adversary";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/* ------------------------------------------------------------------ *
 * Attack the running system from the interface. Each button posts to
 * the real engine; nothing here is a canned response.
 * ------------------------------------------------------------------ */

export function AdversaryConsole({ runId, ready }: { runId: string | null; ready: boolean }) {
  const [busy, setBusy] = useState<AttackId | null>(null);
  const [results, setResults] = useState<Partial<Record<AttackId, AttackOutcome>>>({});
  const [error, setError] = useState<string | null>(null);

  async function attack(id: AttackId) {
    if (!runId) return;
    setBusy(id);
    setError(null);
    try {
      const res = await fetch(`/api/runs/${runId}/adversary`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ attack: id }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "Attack could not run");
      setResults((r) => ({ ...r, [id]: data.outcome as AttackOutcome }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  async function runAll() {
    for (const a of ATTACKS) await attack(a.id);
  }

  const done = Object.values(results).filter(Boolean) as AttackOutcome[];
  const held = done.filter((d) => d.verdict === "held").length;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3 border border-line bg-panel p-4">
        <div className="max-w-[62ch] space-y-1">
          <div className="flex items-center gap-2">
            <ShieldAlert className="h-4 w-4 text-caution" aria-hidden />
            <h3 className="font-display text-sm font-semibold">Attack this run</h3>
          </div>
          <p className="text-xs text-muted">
            Every governance tool asks you to trust its refusals. Try to break these instead.
            Each attack runs against the live engine — the same executor and the same integrity
            check the test suite uses. Your run is not modified.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {done.length > 0 && (
            <span className="font-mono text-[11px] text-muted">
              <span className={cn(held === done.length ? "text-clear" : "text-stop")}>
                {held}/{done.length}
              </span>{" "}
              held
            </span>
          )}
          <Button size="sm" onClick={runAll} disabled={!ready || busy !== null}>
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : null}
            Run every attack
          </Button>
        </div>
      </div>

      {error && <p className="border border-stop/40 bg-stop/5 p-3 text-xs text-stop">{error}</p>}

      {!ready && (
        <p className="border border-line bg-panel p-4 text-xs text-muted">
          Assemble a capsule first — there is nothing to attack yet.
        </p>
      )}

      <ul className="space-y-3">
        {ATTACKS.map((a) => {
          const r = results[a.id];
          return (
            <li key={a.id} className="border border-line bg-panel">
              <div className="flex flex-wrap items-start justify-between gap-3 p-4">
                <div className="max-w-[62ch] space-y-1.5">
                  <p className="font-display text-[13px] font-semibold">{a.title}</p>
                  <p className="text-xs text-muted">{a.attempt}</p>
                  <p className="font-mono text-[10px] uppercase tracking-wider text-dim">
                    tests: {a.claim}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  {r && (
                    <span
                      className={cn(
                        "border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider",
                        r.verdict === "held"
                          ? "border-clear/40 bg-clear/10 text-clear"
                          : "border-stop/40 bg-stop/10 text-stop",
                      )}
                    >
                      {r.verdict === "held" ? "Held" : "Breached"}
                    </span>
                  )}
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={!ready || busy !== null}
                    onClick={() => attack(a.id)}
                  >
                    {busy === a.id ? "Running…" : r ? "Run again" : "Attack"}
                  </Button>
                </div>
              </div>

              {r && (
                <div className="border-t border-line bg-ink/40 p-4">
                  <p
                    className={cn(
                      "mb-3 text-[13px]",
                      r.verdict === "held" ? "text-clear" : "text-stop",
                    )}
                  >
                    {r.headline}
                  </p>
                  <dl className="grid gap-x-6 gap-y-1.5 sm:grid-cols-[max-content_1fr]">
                    {r.proof.map((p, i) => (
                      <div key={i} className="contents">
                        <dt className="font-mono text-[10px] uppercase tracking-wider text-dim">
                          {p.label}
                        </dt>
                        <dd className="break-words font-mono text-[11px] text-text/90">{p.value}</dd>
                      </div>
                    ))}
                  </dl>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

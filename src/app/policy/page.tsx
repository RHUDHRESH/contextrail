import { simulateAll } from "@/lib/contextrail/simulate";
import { POLICIES } from "@/lib/contextrail/policy";
import { cn } from "@/lib/utils";

export const dynamic = "force-dynamic";

/* ------------------------------------------------------------------ *
 * Policy Studio.
 *
 * Governance that nobody dares edit stops matching the business within
 * a quarter. Before a service manager changes a rule they ask one
 * question: "if I turn this off, what starts happening?"
 *
 * Every row below is computed by replaying all four fixture workflows
 * with that rule held out and diffing the plans. Nothing is written.
 * ------------------------------------------------------------------ */

const TONE: Record<string, string> = {
  critical: "text-stop",
  high: "text-caution",
  medium: "text-muted",
  low: "text-dim",
};

const OUT: Record<string, string> = {
  refused: "text-stop",
  held: "text-caution",
  allowed: "text-clear",
};

export default async function PolicyStudioPage() {
  const results = simulateAll();
  const load = results.filter((r) => r.changes.length > 0);
  const idle = results.filter((r) => r.changes.length === 0);
  const examined = results[0]?.examined ?? 0;

  return (
    <main className="mx-auto max-w-[1000px] px-6 py-8">
      <header className="mb-7">
        <p className="eyebrow">contextrail · policy studio</p>
        <h1 className="mt-1 font-display text-2xl font-bold tracking-tight">
          What breaks if you turn this rule off?
        </h1>
        <p className="mt-2 max-w-[70ch] text-sm text-muted">
          Twelve policies decide what the agents may do. Each row below was produced by
          replaying every fixture workflow with that rule held out and diffing the resulting
          plans — {examined} actions examined per rule. This is a simulation: no run is
          modified and nothing is executed.
        </p>
      </header>

      {/* ── rules that actually hold something up ── */}
      <section className="mb-8">
        <h2 className="eyebrow mb-3">load-bearing · {load.length} of {POLICIES.length}</h2>
        <ul className="space-y-3">
          {load.map((r) => (
            <li key={r.policyId} className="border border-line bg-panel">
              <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-line px-4 py-3">
                <div>
                  <code className="font-mono text-[11px] text-rail">{r.policyId}</code>
                  <span className="ml-2 text-[13px] font-semibold">{r.policyTitle}</span>
                </div>
                <span className={cn("font-mono text-[10px] uppercase tracking-wider", TONE[r.severity])}>
                  {r.severity} · {r.changes.length} outcome{r.changes.length === 1 ? "" : "s"} move
                </span>
              </div>

              <p className="px-4 pt-3 text-sm text-caution">{r.headline}</p>

              {/* Below sm this becomes a two-line record per DESIGN.md §3.
                  The table form clipped the "now" and "without the rule"
                  columns at 390 — the two columns the page exists for. */}
              <ul className="space-y-2 px-4 pb-4 pt-3 sm:hidden">
                {r.changes.map((c, i) => (
                  <li key={i} className="border border-line bg-ink/40 px-3 py-2.5">
                    <p className="text-[13px] leading-snug">{c.action}</p>
                    <p className="mt-0.5 font-mono text-[10px] text-dim">{c.tool}</p>
                    <p className="mt-2 flex items-center gap-2 font-mono text-[11px]">
                      <span className={OUT[c.before]}>{c.before}</span>
                      <span aria-hidden className="text-dim">&#8594;</span>
                      <span className={OUT[c.after]}>{c.after}</span>
                      <span className="ml-auto truncate text-[10px] text-muted">{c.scenarioLabel}</span>
                    </p>
                  </li>
                ))}
              </ul>

              <div className="hidden px-4 pb-4 pt-3 sm:block">
                <table className="w-full border-collapse text-left">
                  <thead>
                    <tr className="border-b border-line-strong">
                      <th className="eyebrow py-1.5 pr-4 font-normal">workflow</th>
                      <th className="eyebrow py-1.5 pr-4 font-normal">action</th>
                      <th className="eyebrow py-1.5 pr-4 font-normal">now</th>
                      <th className="eyebrow py-1.5 font-normal">without the rule</th>
                    </tr>
                  </thead>
                  <tbody>
                    {r.changes.map((c, i) => (
                      <tr key={i} className="border-b border-line last:border-0">
                        <td className="py-1.5 pr-4 text-xs text-muted">{c.scenarioLabel}</td>
                        <td className="py-1.5 pr-4 text-xs">
                          {c.action}
                          <span className="ml-2 font-mono text-[10px] text-dim">{c.tool}</span>
                        </td>
                        <td className={cn("py-1.5 pr-4 font-mono text-[11px]", OUT[c.before])}>
                          {c.before}
                        </td>
                        <td className={cn("py-1.5 font-mono text-[11px]", OUT[c.after])}>
                          {c.after}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </li>
          ))}
        </ul>
      </section>

      {/* ── the honest half ── */}
      <section>
        <h2 className="eyebrow mb-3">no measured effect · {idle.length}</h2>
        <p className="mb-3 max-w-[70ch] text-xs text-muted">
          These rules change no outcome in the current fixture set. That does not make them
          wrong — a rule can be redundant here, overlap with a stricter one, or simply cover a
          workflow the fixtures never exercise. It does mean nobody should claim they are
          carrying weight without widening the set first.
        </p>
        <ul className="grid gap-2 sm:grid-cols-2">
          {idle.map((r) => (
            <li
              key={r.policyId}
              /* min-w-0: a grid item defaults to min-width:auto, so without
                 this the row grows to fit the title instead of truncating. */
              className="flex min-w-0 items-baseline gap-2 border border-line bg-panel px-3 py-2"
            >
              <code className="shrink-0 font-mono text-[11px] text-dim">{r.policyId}</code>
              <span className="min-w-0 flex-1 truncate text-xs text-muted">{r.policyTitle}</span>
              <span className={cn("shrink-0 font-mono text-[10px] uppercase", TONE[r.severity])}>
                {r.severity}
              </span>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}

import Link from "next/link";
import { ArrowRight, Radio } from "lucide-react";
import { listRuns } from "@/lib/contextrail/store";
import { SCENARIOS } from "@/lib/contextrail/scenarios";
import { AGENTS } from "@/lib/contextrail/agents";
import { Badge } from "@/components/ui/badge";
import { Stat, StatStrip } from "@/components/rail/metrics";
import { Signal, statusTone } from "@/components/rail/signal";
import { AGENT_COLOR, SYSTEM_COLOR, SYSTEM_LABEL, timeAgo } from "@/lib/utils";

export const dynamic = "force-dynamic";

const CONNECTED = ["notion", "gdocs", "slack", "freshservice", "crm", "github", "linear", "hris"] as const;

export default function CommandCenter() {
  const runs = listRuns();
  const pending = runs.flatMap((r) => r.approvals.filter((a) => a.state === "pending").map((a) => ({ a, r })));

  const totals = runs.reduce(
    (acc, r) => ({
      actions: acc.actions + r.metrics.actions_total,
      done: acc.done + r.metrics.actions_completed,
      blocked: acc.blocked + r.metrics.policy_violations_prevented,
      minutes: acc.minutes + r.metrics.minutes_saved,
      handoffs: acc.handoffs + r.metrics.handoffs,
    }),
    { actions: 0, done: 0, blocked: 0, minutes: 0, handoffs: 0 },
  );

  const rate = totals.actions ? Math.round((totals.done / totals.actions) * 100) : 0;

  return (
    <div className="mx-auto max-w-[1180px] px-6 py-8">
      {/* ── masthead ── */}
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="eyebrow">contextrail · control plane</div>
          <h1 className="mt-1.5 font-display text-[26px] font-semibold leading-tight tracking-tight text-text">
            Command Center
          </h1>
          <p className="mt-1 max-w-xl text-[13px] leading-relaxed text-muted">
            Other agents retrieve information. ContextRail turns enterprise knowledge into governed action and carries
            the right context across every handoff.
          </p>
        </div>

        <Link
          href="/request"
          className="inline-flex h-11 items-center gap-2 rounded-md bg-rail px-3.5 text-[13px] font-semibold text-ink transition-colors hover:bg-rail/90 md:h-9"
        >
          New request <ArrowRight className="size-3.5" />
        </Link>
      </header>

      {/* ── impact ── */}
      <StatStrip className="mt-6 grid-cols-2 sm:grid-cols-3 lg:grid-cols-5">
        <Stat label="workflows run" value={runs.length} hint="this tenant" />
        <Stat label="completion rate" value={`${rate}%`} hint={`${totals.done}/${totals.actions} actions`} />
        <Stat label="violations prevented" value={totals.blocked} tone={totals.blocked ? "stop" : "text"} hint="refused with citation" />
        <Stat label="context handoffs" value={totals.handoffs} tone="rail" hint="zero re-derivation" />
        <Stat label="time saved" value={totals.minutes} unit="min" hint="vs manual path" />
      </StatStrip>

      <div className="mt-7 grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        {/* ── left: scenarios + runs ── */}
        <div className="min-w-0 space-y-7">
          <section>
            <SectionHead
              title="Start a workflow"
              note="One rail, different domains — nothing below was special-cased."
            />
            <div className="mt-3 grid gap-2.5 sm:grid-cols-3">
              {SCENARIOS.map((s) => (
                <Link
                  key={s.id}
                  href={`/request?scenario=${s.id}`}
                  className="group panel-raised flex flex-col p-3.5 transition-colors hover:border-rail/45"
                >
                  <div className="eyebrow">{s.domain}</div>
                  <h3 className="mt-1.5 text-[13px] font-semibold tracking-tight text-text">{s.label}</h3>
                  <p className="mt-1.5 flex-1 text-[11.5px] leading-relaxed text-muted">{s.hook}</p>
                  <div className="mt-3 flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.12em] text-dim transition-colors group-hover:text-rail">
                    run it <ArrowRight className="size-3" />
                  </div>
                </Link>
              ))}
            </div>
          </section>

          <section>
            <SectionHead title="Active workflows" note={`${runs.length} on the rail`} />
            {runs.length === 0 ? (
              <div className="mt-3 grid place-items-center rounded-lg border border-dashed border-line px-4 py-12 text-center">
                <Radio className="size-5 text-dim" strokeWidth={1.5} />
                <p className="mt-2 text-[12px] text-muted">No workflows yet.</p>
                <p className="mt-0.5 text-[11.5px] text-dim">Pick a scenario above to put the first capsule on the rail.</p>
              </div>
            ) : (
              <ul className="mt-3 min-w-0 max-w-full space-y-2 overflow-hidden">
                {runs.map((r) => (
                  <li key={r.id} className="min-w-0 max-w-full">
                    <Link href={`/runs/${r.id}`} className="panel block min-w-0 max-w-full overflow-hidden p-3.5 transition-colors hover:border-line-strong">
                      <div className="flex flex-col items-start justify-between gap-3 sm:flex-row sm:gap-4">
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <Signal tone={statusTone(r.status)} />
                            <span className="font-mono text-[10.5px] text-dim">{r.id}</span>
                            <span className="font-mono text-[10.5px] text-dim">· {timeAgo(r.createdAt)}</span>
                          </div>
                          <p className="mt-1 truncate text-[12.5px] text-text">{r.request}</p>
                          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                            {r.capsule.handoff_chain.map((a) => (
                              <span
                                key={a}
                                className="rounded border border-line-strong bg-panel-2 px-1.5 py-px font-mono text-[9.5px]"
                                style={{ color: AGENT_COLOR[a] }}
                              >
                                {AGENTS[a].name}
                              </span>
                            ))}
                          </div>
                        </div>

                        <div className="flex w-full shrink-0 items-center justify-between gap-4 text-left sm:w-auto sm:justify-start sm:text-right">
                          <div>
                            <div className="tabular font-display text-[15px] font-semibold text-text">
                              {r.metrics.actions_completed}/{r.metrics.actions_total}
                            </div>
                            <div className="eyebrow mt-0.5">actions</div>
                          </div>
                          <Badge
                            tone={
                              statusTone(r.status) === "clear" ? "clear" : statusTone(r.status) === "stop" ? "stop" : "caution"
                            }
                          >
                            {r.status.replace("_", " ")}
                          </Badge>
                        </div>
                      </div>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        {/* ── right: queue + connectors ── */}
        <aside className="space-y-6">
          <section>
            <SectionHead title="Approval queue" note={pending.length ? `${pending.length} held` : "clear"} />
            <div className="mt-3 space-y-2">
              {pending.length === 0 ? (
                <div className="rounded-lg border border-dashed border-line px-3 py-6 text-center text-[11.5px] text-dim">
                  Nothing waiting on a human.
                </div>
              ) : (
                pending.map(({ a, r }) => (
                  <Link
                    key={a.id}
                    href={`/runs/${r.id}`}
                    className="block rounded-lg border border-caution/30 bg-caution/[0.04] p-3 transition-colors hover:border-caution/55"
                  >
                    <div className="flex items-center gap-2">
                      <Signal tone="caution" />
                      <span className="font-mono text-[10px] text-dim">{a.policyId}</span>
                    </div>
                    <p className="mt-1 text-[12px] font-medium leading-snug text-text">{a.title}</p>
                    <p className="mt-0.5 font-mono text-[10px] text-caution">{a.approver}</p>
                  </Link>
                ))
              )}
            </div>
          </section>

          <section>
            <SectionHead title="Connected systems" note="8 sources" />
            <div className="panel mt-3 divide-y divide-line">
              {CONNECTED.map((s) => (
                <div key={s} className="flex items-center gap-2.5 px-3 py-2">
                  <span className="size-1.5 rounded-full" style={{ background: SYSTEM_COLOR[s] }} />
                  <span className="flex-1 text-[12px] text-text">{SYSTEM_LABEL[s]}</span>
                  <span className="font-mono text-[9.5px] uppercase tracking-[0.1em] text-clear">live</span>
                </div>
              ))}
            </div>
          </section>

          <section>
            <SectionHead title="Specialist agents" note="capability-routed" />
            <div className="panel mt-3 divide-y divide-line">
              {Object.values(AGENTS).map((a) => (
                <div key={a.id} className="px-3 py-2">
                  <div className="flex items-center gap-2.5">
                    <span className="size-1.5 rounded-full" style={{ background: AGENT_COLOR[a.id] }} />
                    <span className="flex-1 text-[12px] text-text">{a.name}</span>
                    <span className="font-mono text-[9.5px] text-dim">{a.tools.length} tools</span>
                  </div>
                </div>
              ))}
            </div>
          </section>
        </aside>
      </div>
    </div>
  );
}

function SectionHead({ title, note }: { title: string; note?: string }) {
  return (
    <div className="flex flex-col items-start justify-between gap-1.5 border-b border-line pb-2 sm:flex-row sm:items-baseline sm:gap-3">
      <h2 className="font-display text-[13px] font-semibold tracking-tight text-text">{title}</h2>
      {note && <span className="eyebrow">{note}</span>}
    </div>
  );
}

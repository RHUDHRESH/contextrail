import Link from "next/link";
import { ShieldCheck } from "lucide-react";
import { listRuns } from "@/lib/contextrail/store";
import { Badge, riskTone } from "@/components/ui/badge";
import { Signal } from "@/components/rail/signal";
import { Stat, StatStrip } from "@/components/rail/metrics";

export const dynamic = "force-dynamic";

export default function ApprovalCenter() {
  const runs = listRuns();
  const all = runs.flatMap((r) => r.approvals.map((a) => ({ a, r })));
  const pending = all.filter((x) => x.a.state === "pending");
  const decided = all.filter((x) => x.a.state !== "pending");
  const approvedCount = decided.filter((x) => x.a.state === "approved").length;
  const deniedCount = decided.filter((x) => x.a.state === "denied").length;

  return (
    <div className="mx-auto max-w-[980px] px-6 py-8">
      <header>
        <div className="eyebrow">governance</div>
        <h1 className="mt-1.5 font-display text-[26px] font-semibold leading-tight tracking-tight text-text">
          Approval Center
        </h1>
        <p className="mt-1 max-w-xl text-[13px] leading-relaxed text-muted">
          Every privileged action stops here with the policy that held it, the evidence behind it, and the person who
          owns the decision.
        </p>
      </header>

      <StatStrip className="mt-6 grid-cols-3">
        <Stat label="awaiting a human" value={pending.length} tone={pending.length ? "caution" : "text"} />
        {/* Tone follows an actual state, never a sentiment: a zero count is
            not a red outcome. */}
        <Stat label="approved" value={approvedCount} tone={approvedCount > 0 ? "clear" : "text"} />
        <Stat label="denied" value={deniedCount} tone={deniedCount > 0 ? "stop" : "text"} />
      </StatStrip>

      <section className="mt-7">
        <h2 className="border-b border-line pb-2 font-display text-[13px] font-semibold tracking-tight text-text">
          Held for approval
        </h2>
        {pending.length === 0 ? (
          <div className="mt-3 grid place-items-center rounded-lg border border-dashed border-line px-4 py-12 text-center">
            <ShieldCheck className="size-5 text-dim" strokeWidth={1.5} />
            <p className="mt-2 text-[12px] text-muted">The queue is clear.</p>
          </div>
        ) : (
          <ul className="mt-3 space-y-2">
            {pending.map(({ a, r }) => (
              <li key={`${r.id}-${a.id}`}>
                <Link
                  href={`/runs/${r.id}`}
                  className="block rounded-lg border border-caution/30 bg-caution/[0.04] p-3.5 transition-colors hover:border-caution/55"
                >
                  <div className="flex items-center gap-2">
                    <Signal tone="caution" />
                    <span className="font-mono text-[10px] text-dim">
                      {r.id} · {a.id}
                    </span>
                  </div>
                  <p className="mt-1 text-[12.5px] font-semibold tracking-tight text-text">{a.title}</p>
                  <p className="mt-1 text-[11.5px] leading-relaxed text-muted">{a.why}</p>
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    <Badge tone={riskTone(a.risk)}>{a.risk} risk</Badge>
                    <Badge tone="neutral">{a.policyId}</Badge>
                    <span className="font-mono text-[10px] text-caution">{a.approver}</span>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>

      {decided.length > 0 && (
        <section className="mt-7">
          <h2 className="border-b border-line pb-2 font-display text-[13px] font-semibold tracking-tight text-text">
            Decision history
          </h2>
          <ul className="mt-3 space-y-px font-mono text-[11px]">
            {decided.map(({ a, r }) => (
              <li key={`${r.id}-${a.id}`} className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1 rounded px-2 py-2 hover:bg-panel-2/60 sm:grid-cols-[86px_1fr_auto] sm:py-1.5">
                <span className="text-dim">{a.decidedAt ? new Date(a.decidedAt).toLocaleTimeString("en-GB", { hour12: false }) : "—"}</span>
                <span className="order-3 col-span-2 min-w-0 text-muted sm:order-none sm:col-span-1 sm:truncate">
                  <span className="text-dim">{a.approver}</span> {a.state} “{a.title}”
                  {a.note && <span className="text-dim"> — {a.note}</span>}
                </span>
                <Badge tone={a.state === "approved" ? "clear" : "stop"}>{a.state}</Badge>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

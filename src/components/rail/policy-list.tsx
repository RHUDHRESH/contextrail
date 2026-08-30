import { Ban, CircleCheck, ShieldAlert } from "lucide-react";
import type { PolicyDecision } from "@/lib/contextrail/types";
import { SYSTEM_COLOR, SYSTEM_LABEL } from "@/lib/utils";

const EFFECT = {
  allow: { icon: CircleCheck, tone: "text-clear", label: "allow", ring: "border-clear/30" },
  require_approval: { icon: ShieldAlert, tone: "text-caution", label: "approval", ring: "border-caution/30" },
  deny: { icon: Ban, tone: "text-stop", label: "deny", ring: "border-stop/30" },
} as const;

/** Every governance decision shows the sentence it was derived from. */
export function PolicyList({ decisions }: { decisions: PolicyDecision[] }) {
  if (!decisions.length) return <Empty>No policies evaluated yet.</Empty>;

  return (
    <ul className="space-y-2">
      {decisions.map((d) => {
        const e = EFFECT[d.effect];
        const Icon = e.icon;
        return (
          <li key={d.policyId} className={`rounded-lg border bg-panel-2/50 p-3 ${e.ring}`}>
            <div className="flex items-start gap-2.5">
              <Icon className={`mt-[1px] size-4 shrink-0 ${e.tone}`} strokeWidth={1.9} />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <span className="text-[12.5px] font-semibold tracking-tight text-text">{d.title}</span>
                  <span className="font-mono text-[10px] text-dim">{d.policyId}</span>
                  <span className={`font-mono text-[10px] uppercase tracking-[0.1em] ${e.tone}`}>{e.label}</span>
                </div>

                <p className="mt-1 text-[11.5px] leading-relaxed text-muted">{d.reason}</p>

                <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1">
                  <span className="font-mono text-[10px] text-dim">applies to {d.appliesTo}</span>
                  {d.approver && <span className="font-mono text-[10px] text-caution">approver {d.approver}</span>}
                </div>

                {/* the citation is the point — a policy without one is an opinion */}
                <blockquote className="mt-2 rounded-md border border-line-strong bg-ink/35 px-3 py-2 text-[11px] leading-relaxed text-muted italic">
                  “{d.citation.excerpt}”
                  <cite className="mt-0.5 block not-italic font-mono text-[10px]" style={{ color: SYSTEM_COLOR[d.citation.system] }}>
                    {SYSTEM_LABEL[d.citation.system]} · {d.citation.title}
                  </cite>
                </blockquote>
              </div>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid place-items-center rounded-lg border border-dashed border-line px-4 py-10 text-center text-[11.5px] text-dim">
      {children}
    </div>
  );
}

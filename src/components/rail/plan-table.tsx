import { Ban, Lock } from "lucide-react";
import type { ActionPlan } from "@/lib/contextrail/types";
import { AGENTS } from "@/lib/contextrail/agents";
import { Badge, riskTone } from "@/components/ui/badge";
import { AGENT_COLOR, cn } from "@/lib/utils";
import { Empty } from "./policy-list";

export function PlanTable({ plan }: { plan: ActionPlan | null }) {
  if (!plan) return <Empty>The planner has not run yet.</Empty>;

  return (
    <div className="space-y-2">
      {plan.actions.map((a, i) => {
        const blocked = Boolean(a.blockedBy);
        return (
          <div
            key={a.id}
            className={cn(
              "rounded-lg border bg-panel-2/50 p-3",
              blocked ? "border-stop/35 bg-stop/[0.04]" : "border-line",
            )}
          >
            <div className="flex items-start gap-3">
              <span className="tabular mt-[3px] font-mono text-[10px] text-dim">{String(i + 1).padStart(2, "0")}</span>

              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                  <span className={cn("text-[12.5px] font-semibold tracking-tight", blocked ? "text-stop line-through decoration-stop/50" : "text-text")}>
                    {a.title}
                  </span>
                  <code className="rounded bg-panel-3 px-1.5 py-px font-mono text-[10px] text-rail">{a.tool}</code>
                </div>

                <p className="mt-1 text-[11.5px] leading-relaxed text-muted">{a.rationale}</p>

                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  <span
                    className="inline-flex items-center gap-1.5 rounded border border-line-strong bg-panel px-1.5 py-0.5 font-mono text-[10px]"
                    style={{ color: AGENT_COLOR[a.agent] }}
                  >
                    <span className="size-1.5 rounded-full" style={{ background: AGENT_COLOR[a.agent] }} />
                    {AGENTS[a.agent].name}
                  </span>

                  <Badge tone={riskTone(a.risk)}>{a.risk} risk</Badge>

                  {a.approvalRequired && !blocked && (
                    <Badge tone="caution">
                      <Lock className="size-2.5" strokeWidth={2.5} /> {a.approver}
                    </Badge>
                  )}

                  {blocked && (
                    <Badge tone="stop">
                      <Ban className="size-2.5" strokeWidth={2.5} /> {a.blockedBy}
                    </Badge>
                  )}

                  {a.dependsOn.length > 0 && (
                    <span className="font-mono text-[10px] text-dim">after {a.dependsOn.join(", ")}</span>
                  )}
                </div>

                <div className="mt-1.5 font-mono text-[10px] leading-relaxed text-dim">
                  verify: {a.verification}
                  <span className="ml-2 opacity-60">key {a.idempotencyKey}</span>
                </div>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

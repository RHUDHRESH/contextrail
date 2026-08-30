"use client";

import { motion } from "framer-motion";
import { Ban, Lock } from "lucide-react";
import { AGENTS } from "@/lib/contextrail/agents";
import type { ActionPlan, ExecutionRecord } from "@/lib/contextrail/types";
import { Badge, riskTone } from "@/components/ui/badge";
import { AGENT_COLOR, cn } from "@/lib/utils";
import { Empty } from "./evidence-list";

const STATUS_TONE = {
  succeeded: "clear",
  failed: "stop",
  blocked: "stop",
  skipped: "neutral",
  awaiting_approval: "caution",
} as const;

export function PlanList({ plan, executions }: { plan: ActionPlan | null; executions: ExecutionRecord[] }) {
  if (!plan) return <Empty>The plan is generated once governance has run.</Empty>;

  return (
    <div>
      <p className="border-b border-line px-4 py-2.5 text-[12px] text-muted">{plan.summary}</p>
      <ol className="divide-y divide-line">
        {plan.actions.map((a, i) => {
          const exec = executions.find((e) => e.actionId === a.id);
          const agent = AGENTS[a.agent];
          return (
            <motion.li
              key={a.id}
              initial={{ opacity: 0, y: 5 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: Math.min(i * 0.035, 0.22) }}
              className={cn("px-4 py-3", a.blockedBy && "bg-stop/[0.035]")}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-[10px] text-dim">{a.id}</span>
                    <span
                      className={cn(
                        "text-[13px] font-medium",
                        a.blockedBy ? "text-muted line-through decoration-stop/60" : "text-text",
                      )}
                    >
                      {a.title}
                    </span>
                  </div>

                  <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[10px] text-dim">
                    <span className="inline-flex items-center gap-1.5" style={{ color: AGENT_COLOR[a.agent] }}>
                      <span className="size-1.5 rounded-full" style={{ background: AGENT_COLOR[a.agent] }} />
                      {agent.name}
                    </span>
                    <span>{a.tool}</span>
                    {a.dependsOn.length > 0 && <span>after {a.dependsOn.join(", ")}</span>}
                  </div>

                  <p className="mt-1.5 text-[11.5px] leading-relaxed text-muted">{a.rationale}</p>

                  {exec && (
                    <p
                      className={cn(
                        "mt-1.5 rounded-md border px-2.5 py-1.5 text-[11.5px] leading-relaxed",
                        exec.verified ? "border-clear/30 bg-clear/[0.04] text-clear/85" : "border-line-strong text-dim",
                      )}
                    >
                      {exec.verification_note}
                      {exec.attempts > 1 && (
                        <span className="ml-1.5 font-mono text-[10px] text-caution">retried ×{exec.attempts}</span>
                      )}
                    </p>
                  )}
                </div>

                <div className="flex shrink-0 flex-col items-end gap-1.5">
                  {a.blockedBy ? (
                    <Badge tone="stop">
                      <Ban className="size-3" /> {a.blockedBy}
                    </Badge>
                  ) : a.approvalRequired ? (
                    <Badge tone="caution">
                      <Lock className="size-3" /> {a.approver}
                    </Badge>
                  ) : (
                    <Badge tone={riskTone(a.risk)}>{a.risk} risk</Badge>
                  )}
                  {exec && <Badge tone={STATUS_TONE[exec.status]}>{exec.status.replace(/_/g, " ")}</Badge>}
                </div>
              </div>
            </motion.li>
          );
        })}
      </ol>
    </div>
  );
}

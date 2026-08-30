"use client";

import { motion } from "framer-motion";
import type { Decision } from "@/lib/contextrail/types";
import { clock, cn } from "@/lib/utils";
import { Empty } from "./evidence-list";

const KIND_TONE: Record<Decision["kind"], string> = {
  intent_resolved: "bg-rail",
  policy_evaluated: "bg-caution",
  plan_generated: "bg-rail",
  handoff: "bg-linear",
  approval_granted: "bg-clear",
  approval_denied: "bg-stop",
  action_executed: "bg-clear",
  action_blocked: "bg-stop",
  verification: "bg-clear",
};

export function AuditTimeline({ decisions }: { decisions: Decision[] }) {
  if (!decisions.length) return <Empty>Every decision the rail makes is recorded here as it happens.</Empty>;

  return (
    <ol className="relative px-4 py-3">
      <span aria-hidden className="absolute top-4 bottom-4 left-[21px] w-px bg-line" />
      {decisions.map((d, i) => (
        <motion.li
          key={d.id + i}
          initial={{ opacity: 0, x: -4 }}
          animate={{ opacity: 1, x: 0 }}
          className="relative flex gap-3 pb-3 last:pb-0"
        >
          <span className={cn("relative z-10 mt-[5px] size-1.5 shrink-0 rounded-full ring-4 ring-panel", KIND_TONE[d.kind])} />
          <div className="min-w-0 flex-1">
            <div className="flex items-baseline gap-2">
              <span className="font-mono text-[10px] tracking-[0.06em] text-dim uppercase">{d.actor}</span>
              <span className="tabular font-mono text-[10px] text-dim">{clock(d.at)}</span>
            </div>
            <p className="mt-0.5 text-[12px] leading-snug text-muted">{d.summary}</p>
          </div>
        </motion.li>
      ))}
    </ol>
  );
}

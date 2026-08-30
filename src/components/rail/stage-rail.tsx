"use client";

import { STAGES, type StageId } from "@/lib/contextrail/types";
import { Signal, statusTone } from "./signal";
import { cn } from "@/lib/utils";

export type StageState = Record<StageId, { status: "idle" | "running" | "done" | "blocked"; note: string }>;

export const EMPTY_STAGES: StageState = Object.fromEntries(
  STAGES.map((s) => [s.id, { status: "idle" as const, note: s.blurb }]),
) as StageState;

/**
 * The spine of the product. Eight stages, one lamp each. A stage that
 * is blocked stays red for the rest of the run — the rail does not
 * quietly forget that something was refused.
 */
export function StageRail({ state, className }: { state: StageState; className?: string }) {
  return (
    <ol className={cn("relative", className)}>
      {STAGES.map((stage, i) => {
        const s = state[stage.id];
        const done = s.status === "done" || s.status === "blocked";
        const last = i === STAGES.length - 1;

        return (
          <li key={stage.id} className="relative flex gap-3 pb-5 last:pb-0">
            {/* connector */}
            {!last && (
              <span
                className={cn(
                  "absolute left-[5px] top-4 bottom-0 w-[2px]",
                  s.status === "running" ? "rail-active" : done ? "bg-rail-dim" : "bg-line",
                )}
              />
            )}

            <span className="relative z-10 mt-[3px] grid size-3 place-items-center">
              <Signal tone={s.status === "idle" ? "idle" : statusTone(s.status)} size={s.status === "idle" ? 6 : 10} />
            </span>

            <div className="min-w-0 flex-1 -mt-0.5">
              <div className="flex items-baseline gap-2">
                <span
                  className={cn(
                    "text-[12.5px] font-semibold tracking-tight transition-colors",
                    s.status === "idle" ? "text-dim" : "text-text",
                  )}
                >
                  {stage.label}
                </span>
                <span className="eyebrow">{String(i + 1).padStart(2, "0")}</span>
              </div>
              <p
                className={cn(
                  "mt-0.5 text-[11.5px] leading-snug transition-colors",
                  s.status === "idle" ? "text-dim/70" : s.status === "blocked" ? "text-stop/90" : "text-muted",
                )}
              >
                {s.note}
              </p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

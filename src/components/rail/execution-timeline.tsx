import { CircleCheck, CircleSlash, RotateCw, TriangleAlert } from "lucide-react";
import type { ExecutionRecord } from "@/lib/contextrail/types";
import { AGENTS } from "@/lib/contextrail/agents";
import { AGENT_COLOR, cn } from "@/lib/utils";
import { Empty } from "./policy-list";

const ICON = {
  succeeded: { Icon: CircleCheck, tone: "text-clear" },
  failed: { Icon: TriangleAlert, tone: "text-stop" },
  blocked: { Icon: CircleSlash, tone: "text-stop" },
  skipped: { Icon: CircleSlash, tone: "text-caution" },
  awaiting_approval: { Icon: CircleSlash, tone: "text-caution" },
} as const;

export function ExecutionTimeline({ records }: { records: ExecutionRecord[] }) {
  if (!records.length) return <Empty>Nothing has executed yet.</Empty>;

  return (
    <ol className="relative space-y-0">
      {records.map((r, i) => {
        const { Icon, tone } = ICON[r.status];
        const ms = new Date(r.finishedAt).getTime() - new Date(r.startedAt).getTime();
        const last = i === records.length - 1;

        return (
          <li key={r.actionId} className="relative flex gap-3 pb-4 last:pb-0">
            {!last && <span className="absolute left-[7px] top-5 bottom-0 w-px bg-line" />}
            <Icon className={cn("relative z-10 mt-0.5 size-4 shrink-0 bg-ink", tone)} strokeWidth={1.9} />

            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-baseline gap-x-2">
                <code className="font-mono text-[11.5px] text-text">{r.tool}</code>
                <span className={cn("font-mono text-[10px] uppercase tracking-[0.1em]", tone)}>{r.status}</span>
                {r.attempts > 1 && (
                  <span className="inline-flex items-center gap-1 font-mono text-[10px] text-caution">
                    <RotateCw className="size-2.5" strokeWidth={2.5} /> {r.attempts} attempts
                  </span>
                )}
                <span className="tabular font-mono text-[10px] text-dim">{ms}ms</span>
              </div>

              <div className="mt-0.5 flex flex-wrap items-center gap-x-2">
                <span className="font-mono text-[10px]" style={{ color: AGENT_COLOR[r.agent] }}>
                  {AGENTS[r.agent].name}
                </span>
                <span className="text-[11px] text-muted">{r.verification_note}</span>
              </div>

              {r.error && <p className="mt-1 font-mono text-[10.5px] text-stop">{r.error}</p>}

              {r.output && Object.keys(r.output).length > 0 && (
                <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5">
                  {Object.entries(r.output).map(([k, v]) => (
                    <span key={k} className="font-mono text-[10px]">
                      <span className="text-dim">{k}</span>{" "}
                      <span className="text-muted">{typeof v === "object" ? JSON.stringify(v) : String(v)}</span>
                    </span>
                  ))}
                </div>
              )}
            </div>

            {r.verified && (
              <span className="mt-0.5 shrink-0 font-mono text-[10px] text-clear">verified</span>
            )}
          </li>
        );
      })}
    </ol>
  );
}

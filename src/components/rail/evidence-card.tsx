import { AlertTriangle } from "lucide-react";
import type { Evidence } from "@/lib/contextrail/types";
import { SYSTEM_COLOR, SYSTEM_LABEL, cn } from "@/lib/utils";

export function EvidenceCard({ e, compact = false }: { e: Evidence; compact?: boolean }) {
  const color = SYSTEM_COLOR[e.system];
  return (
    <article
      className={cn(
        "group relative rounded-lg border border-line bg-panel-2/60 p-3 transition-colors hover:border-line-strong",
        e.stale && "border-caution/30",
      )}
    >
      <span className="absolute left-0 top-3 bottom-3 w-[2px] rounded-full" style={{ background: color }} />

      <div className="flex items-center justify-between gap-2 pl-2">
        <span className="font-mono text-[10px] uppercase tracking-[0.12em]" style={{ color }}>
          {SYSTEM_LABEL[e.system]}
        </span>
        <span className="tabular font-mono text-[10px] text-dim">{(e.confidence * 100).toFixed(0)}%</span>
      </div>

      <h4 className="mt-1 pl-2 text-[12.5px] font-semibold leading-snug tracking-tight text-text">{e.title}</h4>

      {!compact && (
        <p className="mt-1 pl-2 text-[11.5px] leading-relaxed text-muted line-clamp-3">{e.excerpt}</p>
      )}

      <div className="mt-2 flex items-center gap-2 pl-2">
        <span className="font-mono text-[10px] text-dim">
          verified {new Date(e.lastVerifiedAt).toISOString().slice(0, 10)}
        </span>
        {e.stale && (
          <span className="inline-flex items-center gap-1 font-mono text-[10px] text-caution">
            <AlertTriangle className="size-3" strokeWidth={2} /> past freshness budget
          </span>
        )}
      </div>
    </article>
  );
}

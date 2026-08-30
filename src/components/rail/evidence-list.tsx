"use client";

import { motion } from "framer-motion";
import { AlertTriangle, ExternalLink } from "lucide-react";
import type { Evidence } from "@/lib/contextrail/types";
import { SYSTEM_COLOR, SYSTEM_LABEL, cn } from "@/lib/utils";

export function EvidenceList({ evidence }: { evidence: Evidence[] }) {
  if (!evidence.length) {
    return <Empty>Sources appear here as each connector responds.</Empty>;
  }

  return (
    <ul className="divide-y divide-line">
      {evidence.map((e, i) => (
        <motion.li
          key={e.id}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: Math.min(i * 0.03, 0.2) }}
          className="px-4 py-3"
        >
          <div className="flex items-start gap-3">
            <span
              aria-hidden
              className="mt-[5px] size-2 shrink-0 rounded-[3px]"
              style={{ background: SYSTEM_COLOR[e.system] }}
            />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="font-mono text-[10px] tracking-[0.1em] uppercase" style={{ color: SYSTEM_COLOR[e.system] }}>
                  {SYSTEM_LABEL[e.system]}
                </span>
                <span className="text-[13px] font-medium text-text">{e.title}</span>
                {e.stale && (
                  <span className="inline-flex items-center gap-1 font-mono text-[9px] tracking-[0.1em] text-caution uppercase">
                    <AlertTriangle className="size-3" /> stale
                  </span>
                )}
              </div>
              <p className="mt-1 text-[12px] leading-relaxed text-muted">{e.excerpt}</p>
              <div className="mt-1.5 flex items-center gap-3 font-mono text-[10px] text-dim">
                <ConfidenceBar value={e.confidence} />
                <span>verified {e.lastVerifiedAt}</span>
                {e.url && (
                  <a
                    href={e.url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 transition-colors hover:text-rail"
                  >
                    open <ExternalLink className="size-2.5" />
                  </a>
                )}
              </div>
            </div>
          </div>
        </motion.li>
      ))}
    </ul>
  );
}

export function ConfidenceBar({ value }: { value: number }) {
  const tone = value >= 0.85 ? "bg-clear" : value >= 0.6 ? "bg-rail" : "bg-caution";
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="h-[3px] w-12 overflow-hidden rounded-full bg-line-strong">
        <span className={cn("block h-full rounded-full", tone)} style={{ width: `${value * 100}%` }} />
      </span>
      <span className="tabular">{value.toFixed(2)}</span>
    </span>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="px-4 py-8 text-center text-[12px] text-dim">{children}</div>;
}

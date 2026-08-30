"use client";

import { useState } from "react";
import { Braces, Layers } from "lucide-react";
import type { ContextCapsule } from "@/lib/contextrail/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { SYSTEM_COLOR, SYSTEM_LABEL, cn } from "@/lib/utils";

/**
 * The Context Capsule rendered as an object rather than a blob of JSON —
 * but the raw view is one click away, because the whole claim is that
 * this thing is portable and inspectable.
 */
export function CapsuleView({ capsule }: { capsule: ContextCapsule }) {
  const [raw, setRaw] = useState(false);

  return (
    <div className="panel-raised overflow-hidden">
      {/* header band */}
      <div className="flex items-center justify-between gap-3 border-b border-line bg-panel-3/50 px-4 py-2.5">
        <div className="flex items-center gap-2.5 min-w-0">
          <Layers className="size-4 shrink-0 text-rail" strokeWidth={1.75} />
          <div className="min-w-0">
            <div className="font-mono text-[11.5px] text-text">{capsule.request_id}</div>
            <div className="eyebrow mt-0.5">context capsule · tenant {capsule.tenant_id}</div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Badge tone={capsule.audit_status === "complete" ? "clear" : capsule.audit_status === "in_review" ? "caution" : "rail"}>
            {capsule.audit_status.replace("_", " ")}
          </Badge>
          <Button variant="quiet" size="icon" onClick={() => setRaw((v) => !v)} aria-label="Toggle raw JSON">
            <Braces className={cn("size-4", raw && "text-rail")} strokeWidth={1.75} />
          </Button>
        </div>
      </div>

      {raw ? (
        <pre className="max-h-[520px] overflow-auto bg-ink/60 p-4 font-mono text-[11px] leading-relaxed text-muted">
          {JSON.stringify(capsule, null, 2)}
        </pre>
      ) : (
        <div className="divide-y divide-line">
          <Row label="intent">
            <span className="font-mono text-[12px] text-text">{capsule.intent}</span>
            <span className="tabular ml-2 font-mono text-[10px] text-dim">
              {(capsule.intent_confidence * 100).toFixed(0)}% confidence
            </span>
          </Row>

          <Row label="requester">
            <span className="text-[12.5px] text-text">{capsule.requester.name}</span>
            <span className="ml-2 text-[11.5px] text-dim">
              {capsule.requester.role} · {capsule.requester.department}
            </span>
          </Row>

          <Row label="subject">
            <div className="flex flex-wrap gap-x-4 gap-y-1">
              {Object.entries(capsule.subject).map(([k, v]) => (
                <span key={k} className="text-[11.5px]">
                  <span className="font-mono text-dim">{k}</span>{" "}
                  <span className="text-text">{typeof v === "object" ? JSON.stringify(v) : String(v)}</span>
                </span>
              ))}
            </div>
          </Row>

          <Row label={`sources · ${capsule.sources.length}`}>
            <div className="flex flex-wrap gap-1.5">
              {capsule.sources.map((s) => (
                <span
                  key={s.id}
                  title={`${s.title} — ${(s.confidence * 100).toFixed(0)}%`}
                  className="inline-flex items-center gap-1.5 rounded border border-line-strong bg-panel-2 px-1.5 py-0.5 font-mono text-[10px]"
                  style={{ color: SYSTEM_COLOR[s.system] }}
                >
                  <span className="size-1.5 rounded-full" style={{ background: SYSTEM_COLOR[s.system] }} />
                  {SYSTEM_LABEL[s.system]}
                  <span className="text-dim">{(s.confidence * 100).toFixed(0)}</span>
                </span>
              ))}
            </div>
          </Row>

          <Row label={`constraints · ${capsule.constraints.length}`}>
            <ul className="space-y-1.5">
              {capsule.constraints.map((c) => (
                <li key={c.id} className="flex gap-2 text-[11.5px] leading-snug">
                  <span
                    className={cn(
                      "mt-[5px] size-1.5 shrink-0 rounded-full",
                      c.severity === "critical" || c.severity === "high" ? "bg-stop" : "bg-caution",
                    )}
                  />
                  <span className="text-text">
                    {c.statement}
                    <span className="ml-1.5 font-mono text-[10px] text-dim">{c.policyId}</span>
                  </span>
                </li>
              ))}
            </ul>
          </Row>

          <Row label={`planned actions · ${capsule.planned_actions.length}`}>
            <ol className="space-y-1">
              {capsule.planned_actions.map((a, i) => (
                <li key={i} className="flex gap-2 text-[11.5px] text-text">
                  <span className="tabular font-mono text-[10px] text-dim">{String(i + 1).padStart(2, "0")}</span>
                  {a}
                </li>
              ))}
            </ol>
          </Row>

          <Row label="handoff chain">
            <div className="flex flex-wrap items-center gap-1.5">
              {capsule.handoff_chain.length === 0 && <span className="text-[11.5px] text-dim">not yet routed</span>}
              {capsule.handoff_chain.map((a, i) => (
                <span key={a} className="flex items-center gap-1.5">
                  {i > 0 && <span className="text-dim">→</span>}
                  <span className="rounded border border-line-strong bg-panel-2 px-1.5 py-0.5 font-mono text-[10px] text-text">
                    {a}
                  </span>
                </span>
              ))}
            </div>
          </Row>

          {capsule.open_blockers.length > 0 && (
            <Row label="open blockers">
              <ul className="space-y-1">
                {capsule.open_blockers.map((b, i) => (
                  <li key={i} className="text-[11.5px] leading-snug text-caution">
                    {b}
                  </li>
                ))}
              </ul>
            </Row>
          )}
        </div>
      )}
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    /* The 128px label gutter is right on desktop and wrong at 390, where
       it leaves the value ~180px and clips identifiers mid-word. Below sm
       the label sits above its value instead. */
    <div className="gap-3 px-4 py-2.5 sm:grid sm:grid-cols-[128px_1fr]">
      <div className="eyebrow pb-1.5 sm:pt-1 sm:pb-0">{label}</div>
      <div className="min-w-0">{children}</div>
    </div>
  );
}

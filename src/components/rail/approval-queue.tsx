"use client";

import { useState } from "react";
import { Check, Loader2, ShieldAlert, X } from "lucide-react";
import type { Approval, PolicyDecision } from "@/lib/contextrail/types";
import { Badge, riskTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { Empty } from "./policy-list";

export function ApprovalQueue({
  approvals,
  policies = [],
  onDecide,
  busy,
}: {
  approvals: Approval[];
  /** The verdicts behind each hold, so the approver never leaves the tab. */
  policies?: PolicyDecision[];
  onDecide?: (id: string, state: "approved" | "denied", note?: string) => void;
  busy?: boolean;
}) {
  if (!approvals.length) return <Empty>Nothing is waiting on a human right now.</Empty>;

  return (
    <ul className="space-y-2.5">
      {approvals.map((a) => (
        <ApprovalCard
          key={a.id}
          approval={a}
          policy={policies.find((p) => p.policyId === a.policyId)}
          onDecide={onDecide}
          busy={busy}
        />
      ))}
    </ul>
  );
}

function ApprovalCard({
  approval: a,
  policy,
  onDecide,
  busy,
}: {
  approval: Approval;
  policy?: PolicyDecision;
  onDecide?: (id: string, state: "approved" | "denied", note?: string) => void;
  busy?: boolean;
}) {
  const [note, setNote] = useState("");
  const [denying, setDenying] = useState(false);
  const pending = a.state === "pending";

  return (
    <li
      className={cn(
        "rounded-lg border p-3.5 transition-colors",
        pending ? "border-caution/35 bg-caution/[0.035]" : "border-line bg-panel-2/40",
      )}
    >
      <div className="flex items-start gap-2.5">
        <ShieldAlert
          className={cn("mt-[1px] size-4 shrink-0", pending ? "text-caution" : "text-dim")}
          strokeWidth={1.9}
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2">
            <span className="text-[12.5px] font-semibold tracking-tight text-text">{a.title}</span>
            <span className="font-mono text-[10px] text-dim">{a.id}</span>
          </div>

          <p className="mt-1 text-[11.5px] leading-relaxed text-muted">{a.why}</p>

          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <Badge tone={riskTone(a.risk)}>{a.risk} risk</Badge>
            <Badge tone="neutral">{a.policyId}</Badge>
            <span className="font-mono text-[10px] text-dim">approver {a.approver}</span>
          </div>

          {pending ? (
            <div className="mt-3">
              {/* The decision is permanent and lands in a hash-chained
                  record. Say what it does before asking for it. */}
              <p className="border-l-0 border-t border-line pt-2.5 text-[12px] leading-relaxed text-text">
                Approving grants <span className="font-medium">{a.title.toLowerCase()}</span>. It is
                recorded against <span className="font-mono text-[11px]">{a.approver}</span> under{" "}
                <span className="font-mono text-[11px]">{a.policyId}</span> and cannot be edited
                afterwards.
              </p>

              <label htmlFor={`reason-${a.id}`} className="mt-3 block text-[11px] font-medium text-muted">
                Reason for the record
                {denying && <span className="text-caution"> · required to deny</span>}
              </label>
              <input
                id={`reason-${a.id}`}
                value={note}
                onChange={(e) => setNote(e.target.value)}
                aria-describedby={`reason-hint-${a.id}`}
                className="mt-1.5 h-11 w-full rounded-md border border-line-strong bg-panel px-2.5 text-[12.5px] text-text placeholder:text-muted focus:border-rail/60 md:h-9"
              />
              <p id={`reason-hint-${a.id}`} className="mt-1 text-[11px] text-muted">
                Travels with the capsule to every downstream agent.
              </p>

              {policy && (
                <section className="mt-3 border-t border-line pt-3">
                  <h4 className="eyebrow">the rule that put this on hold</h4>
                  <p className="mt-1.5 text-[12px] leading-relaxed text-muted">{policy.reason}</p>
                  <figure className="mt-2 border border-line bg-ink/50 px-3 py-2">
                    <blockquote className="text-[12px] leading-relaxed text-text/90">
                      “{policy.citation.excerpt}”
                    </blockquote>
                    <figcaption className="mt-1.5 font-mono text-[10px] text-dim">
                      {policy.citation.title} · {policy.citation.system} · applies to{" "}
                      {policy.appliesTo}
                    </figcaption>
                  </figure>
                </section>
              )}

              <div className="mt-3 flex flex-wrap items-center gap-2">
                <Button
                  disabled={busy}
                  onClick={() => onDecide?.(a.id, "approved", note || undefined)}
                >
                  {busy ? <Loader2 className="size-3.5 animate-spin" /> : <Check className="size-3.5" />}
                  {busy ? "Recording…" : "Approve"}
                </Button>
                {denying ? (
                  <>
                    <Button
                      variant="stop"
                      disabled={busy || note.trim().length === 0}
                      onClick={() => onDecide?.(a.id, "denied", note.trim())}
                    >
                      <X className="size-3.5" /> Confirm deny
                    </Button>
                    <Button variant="quiet" disabled={busy} onClick={() => setDenying(false)}>
                      Cancel
                    </Button>
                  </>
                ) : (
                  <Button variant="ghost" disabled={busy} onClick={() => setDenying(true)}>
                    Deny…
                  </Button>
                )}
              </div>
            </div>
          ) : (
            <div className="mt-2.5 flex items-center gap-2 border-t border-line pt-2">
              <Badge tone={a.state === "approved" ? "clear" : "stop"}>{a.state}</Badge>
              <span className="font-mono text-[10px] text-dim">
                {a.approver} · {a.decidedAt ? new Date(a.decidedAt).toLocaleTimeString("en-GB", { hour12: false }) : ""}
              </span>
              {a.note && <span className="truncate text-[11px] text-muted">“{a.note}”</span>}
            </div>
          )}
        </div>
      </div>
    </li>
  );
}

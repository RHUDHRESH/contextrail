"use client";

import { motion } from "framer-motion";
import { Check, ShieldAlert, X } from "lucide-react";
import type { Approval } from "@/lib/contextrail/types";
import { Badge, riskTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { Empty } from "./evidence-list";

type Props = {
  approvals: Approval[];
  onDecide: (approvalId: string, decision: "approved" | "denied") => void;
  readOnly?: boolean;
};

export function ApprovalPanel({ approvals, onDecide, readOnly }: Props) {
  if (!approvals.length) return <Empty>No privileged actions in this plan — nothing is held.</Empty>;

  return (
    <ul className="divide-y divide-line">
      {approvals.map((a) => (
        <motion.li
          key={a.id}
          layout
          className={cn("px-4 py-3.5", a.state === "pending" && "bg-caution/[0.04]")}
        >
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <ShieldAlert
                  className={cn(
                    "size-3.5 shrink-0",
                    a.state === "pending" ? "text-caution" : a.state === "approved" ? "text-clear" : "text-stop",
                  )}
                />
                <span className="text-[13px] font-medium text-text">{a.title}</span>
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-2">
                <Badge tone={riskTone(a.risk)}>{a.risk} risk</Badge>
                <Badge>{a.policyId}</Badge>
                <span className="font-mono text-[10px] tracking-[0.08em] text-dim uppercase">
                  approver — {a.approver}
                </span>
              </div>
              <p className="mt-2 text-[11.5px] leading-relaxed text-muted">{a.why}</p>
            </div>

            <div className="flex shrink-0 items-center gap-1.5">
              {a.state === "pending" && !readOnly ? (
                <>
                  <Button size="sm" variant="clear" onClick={() => onDecide(a.id, "approved")}>
                    <Check className="size-3.5" /> Approve
                  </Button>
                  <Button size="sm" variant="stop" onClick={() => onDecide(a.id, "denied")}>
                    <X className="size-3.5" /> Deny
                  </Button>
                </>
              ) : (
                <Badge tone={a.state === "approved" ? "clear" : a.state === "denied" ? "stop" : "caution"}>
                  {a.state}
                </Badge>
              )}
            </div>
          </div>
        </motion.li>
      ))}
    </ul>
  );
}

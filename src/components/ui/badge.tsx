import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.1em] whitespace-nowrap",
  {
    variants: {
      tone: {
        neutral: "border-line-strong bg-panel-2 text-muted",
        rail: "border-rail/40 bg-rail/10 text-rail",
        clear: "border-clear/40 bg-clear/10 text-clear",
        caution: "border-caution/40 bg-caution/10 text-caution",
        stop: "border-stop/40 bg-stop/10 text-stop",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export function Badge({
  className,
  tone,
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}

/** Risk maps onto signal colour, never onto an arbitrary palette. */
export function riskTone(risk: string): "neutral" | "caution" | "stop" {
  if (risk === "critical") return "stop";
  if (risk === "high" || risk === "medium") return "caution";
  return "neutral";
}

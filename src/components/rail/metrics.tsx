import { cn } from "@/lib/utils";

/* ------------------------------------------------------------------ *
 * Stat tiles. One number, one label, one optional line of context —
 * the tone carries the signal meaning, so a figure is never coloured
 * for decoration.
 * ------------------------------------------------------------------ */

export type StatTone = "text" | "clear" | "caution" | "stop" | "rail";

const TONE: Record<StatTone, string> = {
  text: "text-text",
  clear: "text-clear",
  caution: "text-caution",
  stop: "text-stop",
  rail: "text-rail",
};

export function StatStrip({ className, children }: { className?: string; children: React.ReactNode }) {
  return (
    <div className={cn("grid gap-px overflow-hidden rounded-lg border border-line bg-line", className)}>{children}</div>
  );
}

export function Stat({
  label,
  value,
  unit,
  hint,
  tone = "text",
}: {
  label: string;
  value: string | number;
  unit?: string;
  hint?: string;
  tone?: StatTone;
}) {
  return (
    <div className="bg-panel px-3.5 py-3 last:col-span-2 sm:last:col-span-1">
      <div className="eyebrow">{label}</div>
      <div className={cn("tabular mt-1.5 flex items-baseline gap-1 font-display leading-none font-bold", TONE[tone])}>
        <span className="text-2xl">{value}</span>
        {unit && <span className="text-[11px] font-medium text-dim">{unit}</span>}
      </div>
      {hint && <div className="mt-1.5 text-[12px] leading-snug text-muted md:text-[11px] md:text-dim">{hint}</div>}
    </div>
  );
}

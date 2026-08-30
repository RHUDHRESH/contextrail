import { cn } from "@/lib/utils";

/* ------------------------------------------------------------------ *
 * A railway signal lamp. Green is clear, amber is held for a human,
 * red is stopped by policy — and those three colours mean nothing else
 * anywhere in the interface. "live" is the occupied-block state: the
 * rail is moving, so the lamp pulses.
 * ------------------------------------------------------------------ */

export type SignalTone = "clear" | "caution" | "stop" | "rail" | "live" | "idle";

const LAMP: Record<SignalTone, string> = {
  clear: "bg-clear text-clear",
  caution: "bg-caution text-caution",
  stop: "bg-stop text-stop",
  rail: "bg-rail text-rail",
  live: "bg-rail text-rail lamp-live",
  idle: "bg-line-strong text-line-strong",
};

export function Signal({
  tone = "idle",
  live,
  size = 8,
  className,
  label,
}: {
  tone?: SignalTone;
  /** Force the pulse on a tone that is not already "live". */
  live?: boolean;
  size?: number;
  className?: string;
  label?: string;
}) {
  return (
    <span
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      style={{ width: size, height: size }}
      className={cn("inline-block shrink-0 rounded-full", LAMP[tone], live && "lamp-live", className)}
    />
  );
}

/**
 * Map a status onto the signal it should show. Accepts run statuses,
 * stage statuses, and the console's own phase, because all three are
 * rendered through the same lamp.
 */
export function statusTone(status: string): SignalTone {
  switch (status) {
    case "complete":
    case "done":
      return "clear";
    case "failed":
    case "blocked":
      return "stop";
    case "partial":
    case "awaiting_approval":
      return "caution";
    case "executing":
    case "assembling":
    case "running":
      return "live";
    default:
      return "idle";
  }
}

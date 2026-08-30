import { cn } from "@/lib/utils";

export function Progress({ value, className, tone = "var(--color-rail)" }: { value: number; className?: string; tone?: string }) {
  return (
    <div className={cn("h-1 w-full overflow-hidden rounded-full bg-line", className)}>
      <div
        className="h-full rounded-full transition-[width] duration-500 ease-out"
        style={{ width: `${Math.max(0, Math.min(100, value))}%`, background: tone }}
      />
    </div>
  );
}

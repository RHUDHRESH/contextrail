import { cn } from "@/lib/utils";

export function Separator({ className, vertical = false }: { className?: string; vertical?: boolean }) {
  return (
    <div
      role="separator"
      className={cn(vertical ? "w-px self-stretch" : "h-px w-full", "bg-line shrink-0", className)}
    />
  );
}

"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Boxes, GitBranch, LayoutGrid, ShieldCheck, SquarePen, Scale } from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Command Center", icon: LayoutGrid },
  { href: "/request", label: "New Request", icon: SquarePen },
  { href: "/approvals", label: "Approval Center", icon: ShieldCheck },
  { href: "/policy", label: "Policy Studio", icon: Scale },
  { href: "/skills", label: "Skills & Tools", icon: Boxes },
] as const;

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="flex min-h-dvh">
      {/* The rail itself: a 60px vertical strip that never moves. */}
      <nav className="sticky top-0 flex h-dvh w-[60px] shrink-0 flex-col items-center gap-1 border-r border-line bg-panel/60 py-4 backdrop-blur">
        <Link href="/" className="mb-4 grid size-11 place-items-center md:size-9" aria-label="ContextRail home">
          <Mark />
        </Link>

        {NAV.map(({ href, label, icon: Icon }) => {
          const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
          return (
            <Tooltip key={href}>
              <TooltipTrigger asChild>
                <Link
                  href={href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "relative grid size-11 place-items-center rounded-lg transition-colors md:size-9",
                    active ? "bg-rail/12 text-rail" : "text-dim hover:bg-panel-2 hover:text-muted",
                  )}
                >
                  {active && (
                    <span className="absolute -left-[13px] top-1/2 h-5 w-[2px] -translate-y-1/2 rounded-full bg-rail" />
                  )}
                  <Icon className="size-[17px]" strokeWidth={1.75} />
                </Link>
              </TooltipTrigger>
              <TooltipContent side="right">{label}</TooltipContent>
            </Tooltip>
          );
        })}

        <div className="mt-auto flex flex-col items-center gap-2">
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="grid size-11 place-items-center rounded-lg text-dim md:size-9">
                <GitBranch className="size-[15px]" strokeWidth={1.75} />
              </span>
            </TooltipTrigger>
            <TooltipContent side="right">
              Tenant <span className="font-mono">acme-corp</span> · 8 systems connected
            </TooltipContent>
          </Tooltip>
        </div>
      </nav>

      <main className="min-w-0 flex-1">{children}</main>
    </div>
  );
}

/* The mark: two rails converging on a capsule. */
function Mark() {
  return (
    <svg viewBox="0 0 24 24" className="size-[22px]" fill="none" aria-hidden>
      <path d="M4 21V9.5C4 6 6.7 3 12 3s8 3 8 6.5V21" stroke="var(--color-rail-dim)" strokeWidth="1.4" />
      <path d="M9 21v-9c0-1.9 1.2-3.2 3-3.2s3 1.3 3 3.2v9" stroke="var(--color-rail)" strokeWidth="1.4" />
      <rect x="9.6" y="12.4" width="4.8" height="6" rx="2.4" fill="var(--color-clear)" />
    </svg>
  );
}

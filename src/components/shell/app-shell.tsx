"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { Menu, Plus, X } from "lucide-react";

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  return <div className="min-h-dvh">
    <header className="sticky top-0 z-30 border-b border-line bg-ink/95 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-[1160px] items-center gap-5 px-5 md:px-8">
        <Link href="/" className="mr-auto text-[17px] font-semibold tracking-tight text-text">Context<span className="text-rail">Rail</span></Link>
        <nav aria-label="Primary navigation" className="hidden items-center gap-1 sm:flex">
          <Link href="/" aria-current={pathname === "/" ? "page" : undefined} className={`rounded-lg px-3 py-2 text-sm ${pathname === "/" ? "bg-panel-2 text-text" : "text-muted hover:text-text"}`}>Home</Link>
          <Link href="/requests" aria-current={pathname === "/requests" ? "page" : undefined} className={`rounded-lg px-3 py-2 text-sm ${pathname === "/requests" ? "bg-panel-2 text-text" : "text-muted hover:text-text"}`}>My requests</Link>
        </nav>
        {pathname !== "/" && pathname !== "/request" && pathname !== "/requests" && <Link href="/request" className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-rail px-3 text-sm font-semibold text-panel hover:bg-rail/90"><Plus className="size-4" /> New</Link>}
        <div className="relative">
          <button type="button" onClick={() => setOpen((value) => !value)} aria-label="Open menu" aria-expanded={open} className="grid size-9 place-items-center rounded-lg border border-line-strong text-muted hover:text-text">{open ? <X className="size-4" /> : <Menu className="size-4" />}</button>
          {open && <nav aria-label="More" className="absolute right-0 top-11 w-48 rounded-xl border border-line-strong bg-panel p-1.5 shadow-xl">
            <Link href="/requests" onClick={() => setOpen(false)} className="block rounded-lg px-3 py-2 text-sm text-text hover:bg-panel-2 sm:hidden">My requests</Link>
            <Link href="/approvals" onClick={() => setOpen(false)} className="block rounded-lg px-3 py-2 text-sm text-text hover:bg-panel-2">Approvals</Link>
            <Link href="/policy" onClick={() => setOpen(false)} className="block rounded-lg px-3 py-2 text-sm text-text hover:bg-panel-2">Policy</Link>
            <Link href="/skills" onClick={() => setOpen(false)} className="block rounded-lg px-3 py-2 text-sm text-text hover:bg-panel-2">Tools</Link>
          </nav>}
        </div>
      </div>
    </header>
    <main>{children}</main>
  </div>;
}

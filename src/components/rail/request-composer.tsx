"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowRight, CornerDownLeft } from "lucide-react";
import { SCENARIOS, getScenario } from "@/lib/contextrail/scenarios";
import { RunConsole } from "./run-console";

/* ------------------------------------------------------------------ *
 * The entry point: one plain-language box, three prepared scenarios.
 * Once a request is submitted the composer hands off to RunConsole,
 * which owns the live rail from there.
 * ------------------------------------------------------------------ */

type Launch = { request: string; requesterId?: string; scenarioId?: string | null };

const REQUESTERS = [
  { id: "U-2201", label: "Marc Liu · Engineering Manager" },
  { id: "U-3310", label: "Alicia Fenn · Customer Success" },
  { id: "U-1120", label: "Priyanka Rao · IT Provisioning" },
];

export function RequestComposer({ preset }: { preset?: string | null }) {
  const seeded = getScenario(preset);
  const [launch, setLaunch] = useState<Launch | null>(
    seeded ? { request: seeded.request, requesterId: seeded.requesterId, scenarioId: seeded.id } : null,
  );
  const [request, setRequest] = useState(seeded?.request ?? "");
  const [requesterId, setRequesterId] = useState(seeded?.requesterId ?? "U-2201");

  if (launch) return <RunConsole autoStart={launch} />;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (request.trim().length < 8) return;
    setLaunch({ request: request.trim(), requesterId, scenarioId: null });
  };

  const runScenario = (id: string) => {
    const s = getScenario(id);
    if (!s) return;
    setLaunch({ request: s.request, requesterId: s.requesterId, scenarioId: s.id });
  };

  return (
    <div className="mx-auto max-w-[1100px] px-5 py-6 md:px-8 md:py-10">
      <AnimatePresence initial={false}>
        <motion.header initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="mb-7">
          <div className="eyebrow">New request</div>
          <h1 className="mt-2 max-w-3xl font-display text-[28px] leading-[1.08] font-bold tracking-tight md:text-[38px] md:leading-[1.12]">
            Say what needs to happen.
            <br />
            <span className="text-muted">The rail works out what that means, and what it is allowed to do.</span>
          </h1>
        </motion.header>
      </AnimatePresence>

      <form onSubmit={submit}>
        <div className="panel-raised relative overflow-hidden">
          <textarea
            value={request}
            onChange={(e) => setRequest(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit(e);
            }}
            rows={3}
            placeholder="Priya joins engineering on Monday. Give her everything she needs to start."
            aria-label="Describe the request"
            className="w-full resize-none bg-transparent px-4 pt-4 pb-2 text-[15px] leading-relaxed text-text placeholder:text-dim"
          />
          <div className="flex flex-col items-stretch justify-between gap-3 border-t border-line px-3 py-3 sm:flex-row sm:items-center sm:py-2">
            <label className="flex flex-col items-stretch gap-2 sm:flex-row sm:items-center">
              <span className="eyebrow">Requesting as</span>
              <select
                value={requesterId}
                onChange={(e) => setRequesterId(e.target.value)}
                className="h-11 w-full rounded border border-line-strong bg-panel-2 px-3 font-mono text-[14px] text-muted sm:w-auto md:h-7 md:px-2 md:text-[11px]"
              >
                {REQUESTERS.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.label}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="submit"
              disabled={request.trim().length < 8}
              className="inline-flex h-11 items-center justify-center gap-2 rounded-md bg-rail px-3.5 text-[13px] font-semibold text-ink transition-colors hover:bg-rail/90 disabled:pointer-events-none disabled:opacity-45 md:h-9"
            >
              Run the rail
              <CornerDownLeft className="size-3.5" />
            </button>
          </div>
        </div>
      </form>

      <section className="mt-8">
        <div className="eyebrow mb-3">Or run a prepared scenario</div>
        <div className="grid gap-3 md:grid-cols-3">
          {SCENARIOS.map((s) => (
            <button
              key={s.id}
              onClick={() => runScenario(s.id)}
              className="panel group flex flex-col p-4 text-left transition-colors hover:border-rail/45 hover:bg-panel-2"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-display text-[14px] font-semibold tracking-tight">{s.label}</span>
                <ArrowRight className="size-3.5 shrink-0 text-dim transition-transform group-hover:translate-x-0.5 group-hover:text-rail" />
              </div>
              <div className="eyebrow mt-1.5">{s.domain}</div>
              <p className="mt-2.5 flex-1 text-[14px] leading-relaxed text-muted md:text-[12px]">{s.hook}</p>
              <p className="mt-3 border-t border-line pt-2 text-[13px] leading-relaxed text-muted md:text-[11px] md:text-dim">{s.proves}</p>
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}

"use client";

import { useEffect, useState } from "react";
import { ArrowRight, ChevronDown } from "lucide-react";

type Row = { action_id: string; label: string; verdict: string; state: string; clause: string; connector_mode: string };
type RunView = {
  run_id: string;
  status: string;
  request_text: string;
  subject: string | null;
  rows: Row[];
  modes: Record<string, string>;
  needs: { question?: string; candidates?: { display_name: string }[] }[];
};

const example = "Give Anil the same access as Rahul Mehta";

function title(status: string) {
  if (status === "done") return "Done";
  if (status === "awaiting_approval") return "Approval needed";
  if (status === "needs_input") return "More information needed";
  if (status === "partial") return "Partly done";
  return status.replaceAll("_", " ");
}

export default function EngineDemoPage() {
  const [available, setAvailable] = useState<boolean | null>(null);
  const [request, setRequest] = useState(example);
  const [run, setRun] = useState<RunView | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch("/api/engine-demo", { cache: "no-store" })
      .then((res) => res.json())
      .then((body: { available: boolean }) => setAvailable(body.available))
      .catch(() => setAvailable(false));
  }, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true); setError(""); setRun(null);
    try {
      const response = await fetch("/api/engine-demo", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ request }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error ?? "The engine could not finish this request.");
      setRun(body as RunView);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not run the request.");
    } finally { setBusy(false); }
  }

  return <div className="mx-auto max-w-[760px] px-5 pb-20 pt-12 md:px-8 md:pt-24">
    <p className="text-sm font-medium text-rail">Local engine demo</p>
    <h1 className="mt-3 font-display text-[40px] leading-[1.13] text-text md:text-[54px]">See a real run</h1>
    <p className="mt-4 text-[16px] leading-relaxed text-muted">This sends a request through the Python engine, database, policy checks, and connected tools. Each tool reports whether it used live or sample data.</p>
    <form onSubmit={submit} className="mt-9 rounded-[20px] border border-line-strong bg-panel p-4 shadow-[0_12px_40px_rgba(70,53,36,.07)] md:p-5">
      <label htmlFor="engine-request" className="sr-only">Request for the engine</label>
      <textarea id="engine-request" value={request} onChange={(event) => setRequest(event.target.value)} rows={3} className="w-full resize-y bg-transparent text-[17px] leading-7 text-text outline-none" />
      <div className="mt-3 flex items-center justify-between gap-3 border-t border-line pt-4">
        <span className="text-xs text-muted">{available === null ? "Checking engine…" : available ? "Engine ready" : "Engine offline"}</span>
        <button type="submit" disabled={!available || busy || request.trim().length < 8} className="inline-flex h-10 items-center gap-2 rounded-lg bg-rail px-5 text-sm font-semibold text-panel disabled:cursor-not-allowed disabled:opacity-40">{busy ? "Running…" : "Run request"}<ArrowRight className="size-4" /></button>
      </div>
    </form>
    {!available && available !== null && <p role="status" className="mt-4 text-sm text-muted">Start the local pilot engine to use this demo.</p>}
    {error && <p role="alert" className="mt-4 rounded-xl border border-stop/40 bg-stop/5 p-4 text-sm text-text">{error}</p>}
    {run && <section className="mt-8 rounded-2xl border border-line-strong bg-panel p-5" aria-label="Engine result">
      <p className="text-sm font-medium text-rail">Run {run.run_id.slice(0, 8)}</p>
      <h2 className="mt-2 font-display text-3xl text-text">{title(run.status)}</h2>
      <p className="mt-2 text-sm text-muted">{run.subject ? `For ${run.subject}. ` : ""}{run.rows.length} proposed actions, {run.rows.filter((row) => row.state === "verified").length} verified.</p>
      {run.needs.length > 0 && <p className="mt-4 text-sm text-text">{run.needs[0].question ?? "The engine needs a clearer person or request."}</p>}
      <div className="mt-5 space-y-2">{run.rows.map((row) => <div key={row.action_id} className="flex items-start justify-between gap-4 rounded-xl bg-panel-2 px-4 py-3 text-sm"><span className="text-text">{row.label}</span><span className="shrink-0 text-muted">{row.verdict} · {row.state}</span></div>)}</div>
      <details className="mt-5 border-t border-line pt-4"><summary className="flex cursor-pointer list-none items-center justify-between text-sm font-medium text-text">Details <ChevronDown className="size-4" /></summary>
        <p className="mt-3 text-xs text-muted">Connector modes: {Object.entries(run.modes).map(([name, mode]) => `${name} ${mode}`).join(" · ")}</p>
        {run.rows.map((row) => <p key={row.action_id} className="mt-3 text-xs leading-relaxed text-muted">{row.label}: {row.clause} ({row.connector_mode})</p>)}
      </details>
    </section>}
    <p className="mt-5 text-xs leading-relaxed text-dim">Local development only. Sample people and entitlements are used; a completed row does not mean production access was changed.</p>
  </div>;
}

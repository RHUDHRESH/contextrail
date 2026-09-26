"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, ArrowRight, ChevronDown, FileText, Play } from "lucide-react";
import type { RailEvent, Run } from "@/lib/contextrail/types";
import { ApprovalQueue } from "./approval-queue";

type Launch = { request: string; requesterId?: string; scenarioId?: string | null };

async function consume(res: Response, onEvent: (event: RailEvent) => void) {
  const reader = res.body?.getReader();
  if (!reader) throw new Error("No response received.");
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const line = frame.trim();
      if (!line.startsWith("data:")) continue;
      const event = JSON.parse(line.slice(5).trim()) as RailEvent | { type: "end" };
      if (event.type === "end") continue;
      if (event.type === "error") throw new Error(event.message);
      onEvent(event);
    }
  }
}

function status(run: Run | null, loading: boolean) {
  if (loading) return { title: "Putting your request together", text: "Checking the sample records and preparing next steps." };
  if (!run) return { title: "Preparing your request", text: "This usually takes a few seconds." };
  if (run.approvals.some((item) => item.state === "pending")) return { title: "Approval needed", text: "Someone needs to review a step before this can continue." };
  if (run.status === "complete") return { title: "Done", text: "The simulated workflow has finished." };
  if (run.status === "partial") return { title: "Partly done", text: "Some steps could not be completed. Open details to see why." };
  if (run.status === "failed") return { title: "Needs attention", text: "The simulated workflow stopped. Open details to see why." };
  if (run.executions.length) return { title: "Work in progress", text: "Some actions have run in the sample environment." };
  return { title: "Ready to continue", text: "Review the proposed next steps, then continue the simulation." };
}

export function RunConsole({ initialRun, autoStart }: { initialRun?: Run; autoStart?: Launch }) {
  const router = useRouter();
  const started = useRef(false);
  const [run, setRun] = useState<Run | null>(initialRun ?? null);
  const [loading, setLoading] = useState(Boolean(autoStart));
  const [busy, setBusy] = useState(false);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [error, setError] = useState("");
  const [progress, setProgress] = useState("");

  useEffect(() => {
    if (!autoStart || started.current) return;
    started.current = true;
    let active = true;
    async function start() {
      try {
        const res = await fetch("/api/runs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(autoStart) });
        if (!res.ok) throw new Error(`Request failed (${res.status}).`);
        let finalRun: Run | null = null;
        await consume(res, (event) => {
          if (!active) return;
          if (event.type === "stage" && event.status === "running") setProgress(event.note);
          if (event.type === "run") { finalRun = event.run; setRun(event.run); }
        });
        if (!finalRun) throw new Error("The request ended without a result.");
        if (active) { setLoading(false); router.replace(`/runs/${(finalRun as Run).id}`); }
      } catch (cause) {
        if (active) { setLoading(false); setError(cause instanceof Error ? cause.message : "Could not prepare request."); }
      }
    }
    void start();
    return () => { active = false; };
  }, [autoStart, router]);

  const decide = useCallback(async (approvalId: string, decision: "approved" | "denied", note?: string) => {
    if (!run) return;
    setBusy(true); setError("");
    try {
      const res = await fetch(`/api/runs/${run.id}/approvals`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ approvalId, state: decision, note }) });
      if (!res.ok) throw new Error(`Decision failed (${res.status}).`);
      const body = (await res.json()) as { run: Run };
      setRun(body.run);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not record decision."); }
    finally { setBusy(false); }
  }, [run]);

  const execute = useCallback(async () => {
    if (!run) return;
    setBusy(true); setError("");
    try {
      const res = await fetch(`/api/runs/${run.id}/execute`, { method: "POST" });
      if (!res.ok) throw new Error(`Could not continue (${res.status}).`);
      let nextRun: Run | null = null;
      await consume(res, (event) => { if (event.type === "run") { nextRun = event.run; setRun(event.run); } });
      if (!nextRun) throw new Error("No updated result was returned.");
      router.refresh();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not continue."); }
    finally { setBusy(false); }
  }, [run, router]);

  const message = status(run, loading);
  const pending = run?.approvals.filter((item) => item.state === "pending") ?? [];
  const hasExecution = Boolean(run?.executions.length);
  const canContinue = Boolean(run && !hasExecution && pending.length === 0 && !busy);
  const requestText = (run?.request ?? autoStart?.request ?? "").split("\n")[0];
  const addedContext = (run?.request ?? autoStart?.request ?? "").split("\n").slice(1);
  return <div className="mx-auto max-w-[760px] px-5 pb-20 pt-10 md:px-8 md:pt-16">
    <Link href="/" className="inline-flex items-center gap-2 text-sm text-muted hover:text-text"><ArrowLeft className="size-4" /> Home</Link>
    <div className="mt-10">
      <div className="flex items-center gap-2"><span className={`size-2.5 rounded-full ${pending.length ? "bg-caution" : run?.status === "complete" ? "bg-clear" : "bg-rail"}`} /><span className="text-sm font-semibold text-muted">{run?.id ?? "New request"} · Demo</span></div>
      <h1 className="mt-4 font-display text-3xl font-semibold tracking-tight text-text md:text-4xl">{message.title}</h1>
      <p className="mt-2 text-[15px] leading-relaxed text-muted">{message.text}</p>
      {loading && <p role="status" className="mt-4 text-sm text-rail">{progress || "Getting started…"}</p>}
    </div>

    <div className="mt-8 rounded-2xl border border-line-strong bg-panel p-5">
      <p className="text-xs font-semibold uppercase tracking-wide text-dim">Your request</p>
      <p className="mt-2 text-base leading-relaxed text-text">{requestText}</p>
      {addedContext.length > 0 && <div className="mt-3 space-y-1 border-t border-line pt-3 text-xs text-muted">{addedContext.map((line) => <p key={line}>{line}</p>)}</div>}
      {run && <p className="mt-2 text-xs text-dim">Simulated using sample people, records, and tools.</p>}
    </div>

    {error && <div role="alert" className="mt-5 rounded-xl border border-stop/40 bg-stop/5 p-4 text-sm text-text">{error}</div>}

    {pending.length > 0 && run && <section className="mt-8 rounded-xl border border-caution/30 bg-caution/5 p-5">
      <h2 className="font-display text-lg font-semibold text-text">Waiting for {pending[0].approver}</h2>
      <p className="mt-1 text-sm text-muted">The next step needs their approval. You can come back to this request later.</p>
      <button type="button" onClick={() => setReviewOpen((value) => !value)} className="mt-3 text-sm text-rail hover:underline">{reviewOpen ? "Hide approval demo" : "Open approval demo"}</button>
      {reviewOpen && <div className="mt-4"><ApprovalQueue approvals={run.approvals} policies={run.policies} onDecide={decide} busy={busy} /></div>}
    </section>}

    {canContinue && <div className="mt-8">
      <button type="button" onClick={execute} className="inline-flex h-11 items-center gap-2 rounded-lg bg-rail px-5 text-sm font-semibold text-ink hover:bg-rail/90"><Play className="size-4" /> Continue demo <ArrowRight className="size-4" /></button>
      <p className="mt-2 text-xs text-dim">Runs actions against sample data only.</p>
    </div>}

    {run && <div className="mt-8">
      <details className="group rounded-xl border border-line bg-panel">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-sm font-medium text-text">Details <ChevronDown className="size-4 text-muted transition-transform group-open:rotate-180" /></summary>
        <div className="space-y-6 border-t border-line px-4 py-5">
          <section><h2 className="text-sm font-semibold text-text">Next steps</h2><ol className="mt-3 space-y-2">{run.plan.actions.map((action) => <li key={action.id} className="rounded-lg bg-panel-2 px-3 py-2 text-sm text-muted">{action.title}{action.blockedBy ? <span className="ml-2 text-stop">Blocked by policy</span> : null}</li>)}</ol></section>
          <section><h2 className="text-sm font-semibold text-text">Why</h2><p className="mt-2 text-sm leading-relaxed text-muted">{run.plan.summary}</p></section>
          <section><h2 className="text-sm font-semibold text-text">Sources and decisions</h2><p className="mt-2 text-sm text-muted">{run.capsule.sources.length} sample sources · {run.audit.length} decisions · {run.policies.length} policy checks</p><Link href={`/runs/${run.id}/receipt`} className="mt-3 inline-flex items-center gap-2 text-sm text-rail hover:underline"><FileText className="size-4" /> Full receipt</Link></section>
        </div>
      </details>
    </div>}
    <p className="mt-8 text-xs text-dim">This page is a fixture demo. No live Freshservice ticket is created, and no outbound call is placed.</p>
  </div>;
}

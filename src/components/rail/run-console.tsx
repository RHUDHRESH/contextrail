"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { FileText, Play, Rewind, ShieldCheck, TriangleAlert } from "lucide-react";
import type {
  ActionPlan,
  Approval,
  ContextCapsule,
  Decision,
  Evidence,
  ExecutionRecord,
  PolicyDecision,
  RailEvent,
  Run,
  StageId,
} from "@/lib/contextrail/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { StageRail, EMPTY_STAGES, type StageState } from "./stage-rail";
import { EvidenceCard } from "./evidence-card";
import { CapsuleView } from "./capsule-view";
import { PolicyList, Empty } from "./policy-list";
import { PlanTable } from "./plan-table";
import { HandoffGraph, HandoffLedger, type HandoffEvent } from "./handoff-graph";
import { ApprovalQueue } from "./approval-queue";
import { ExecutionTimeline } from "./execution-timeline";
import { AuditLog } from "./audit-log";
import { AdversaryConsole } from "./adversary-console";
import { IntegritySeal } from "./integrity-seal";
import { Stat, StatStrip } from "./metrics";
import { statusTone, Signal } from "./signal";
import { cn } from "@/lib/utils";

type State = {
  stages: StageState;
  evidence: Evidence[];
  capsule: ContextCapsule | null;
  policies: PolicyDecision[];
  plan: ActionPlan | null;
  handoffs: HandoffEvent[];
  approvals: Approval[];
  executions: ExecutionRecord[];
  audit: Decision[];
  run: Run | null;
};

const BLANK: State = {
  stages: EMPTY_STAGES,
  evidence: [],
  capsule: null,
  policies: [],
  plan: null,
  handoffs: [],
  approvals: [],
  executions: [],
  audit: [],
  run: null,
};

function hydrate(run: Run): State {
  const stages = { ...EMPTY_STAGES } as StageState;
  (["discover", "compile", "govern", "plan", "handoff"] as StageId[]).forEach((s) => {
    stages[s] = { status: "done", note: stages[s].note };
  });
  if (run.executions.length) {
    stages.execute = { status: "done", note: `${run.metrics.actions_completed} action(s) executed` };
    const verified = run.executions.filter((e) => e.verified).length;
    stages.verify = {
      status: run.metrics.actions_blocked ? "blocked" : "done",
      note: run.metrics.actions_blocked
        ? `${verified} outcome(s) verified · ${run.metrics.actions_blocked} refused by policy`
        : `${verified} outcome(s) verified`,
    };
  }
  stages.approve = {
    status: run.approvals.length === 0 ? "done" : run.approvals.every((a) => a.state !== "pending") ? "done" : "running",
    note: run.approvals.length ? `${run.approvals.length} privileged action(s)` : "No privileged actions",
  };

  return {
    stages,
    evidence: run.capsule.sources,
    capsule: run.capsule,
    policies: run.policies,
    plan: run.plan,
    handoffs: run.capsule.handoff_chain.map((to, i) => {
      const owned = run.plan.actions.filter((a) => a.agent === to && !a.blockedBy);
      return {
        from: i === 0 ? ("ORCHESTRATOR" as const) : run.capsule.handoff_chain[i - 1],
        to,
        carries: [
          `${run.capsule.sources.length} evidence items`,
          `${run.capsule.constraints.length} active constraints`,
          `${run.audit.length} prior decisions`,
          `${owned.length} assigned action(s)`,
          ...(run.capsule.open_blockers.length ? [`${run.capsule.open_blockers.length} open blocker(s)`] : []),
        ],
      };
    }),
    approvals: run.approvals,
    executions: run.executions,
    audit: run.audit,
    run,
  };
}

async function consume(res: Response, onEvent: (e: RailEvent) => void) {
  const reader = res.body?.getReader();
  if (!reader) return;
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
      const payload = JSON.parse(line.slice(5).trim());
      if (payload.type === "end") continue;
      onEvent(payload as RailEvent);
    }
  }
}

export function RunConsole({ initialRun, autoStart }: { initialRun?: Run; autoStart?: { request: string; requesterId?: string; scenarioId?: string | null } }) {
  const router = useRouter();
  const [state, setState] = useState<State>(initialRun ? hydrate(initialRun) : BLANK);
  const [phase, setPhase] = useState<"idle" | "assembling" | "ready" | "executing" | "done">(
    initialRun ? (initialRun.executions.length ? "done" : "ready") : "idle",
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ what: string; detail: string } | null>(null);
  // Tab lives in the URL hash so an operator can send a colleague
  // straight to "the Policy tab of REQ-24082".
  const [tab, setTabState] = useState("capsule");
  useEffect(() => {
    // Deliberate: the hash is client-only, so a lazy initialiser would
    // desync from the server render. Restoring after mount is correct.
    const fromHash = window.location.hash.replace("#", "");
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (fromHash) setTabState(fromHash);
  }, []);
  const setTab = useCallback((next: string) => {
    setTabState(next);
    window.history.replaceState(null, "", `#${next}`);
  }, []);
  const started = useRef(false);

  const apply = useCallback((e: RailEvent) => {
    setState((s) => {
      switch (e.type) {
        case "stage":
          return { ...s, stages: { ...s.stages, [e.stage]: { status: e.status, note: e.note } } };
        case "evidence":
          return { ...s, evidence: [...s.evidence, e.evidence] };
        case "capsule":
          return { ...s, capsule: e.capsule };
        case "policy":
          return { ...s, policies: [...s.policies, e.decision] };
        case "plan":
          return { ...s, plan: e.plan };
        case "handoff":
          return { ...s, handoffs: [...s.handoffs, e] };
        case "approval":
          return { ...s, approvals: [...s.approvals, e.approval] };
        case "execution":
          return { ...s, executions: [...s.executions, e.record] };
        case "audit":
          return { ...s, audit: [...s.audit, e.decision] };
        case "run":
          return { ...s, run: e.run, approvals: e.run.approvals, audit: e.run.audit };
        default:
          return s;
      }
    });
  }, []);

  const start = useCallback(
    async (input: { request: string; requesterId?: string; scenarioId?: string | null }) => {
      setState(BLANK);
      setError(null);
      setPhase("assembling");
      try {
        const res = await fetch("/api/runs", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(input),
        });
        if (!res.ok) throw new Error(`The orchestrator returned ${res.status}.`);
        await consume(res, apply);
        setPhase("ready");
      } catch (e) {
        // A dropped stream used to leave the rail spinning forever with
        // no message. Say what failed and let the operator retry.
        setError({
          what: "The rail stopped before the capsule was complete.",
          detail: e instanceof Error ? e.message : String(e),
        });
        setPhase("idle");
      }
    },
    [apply],
  );

  useEffect(() => {
    if (autoStart && !started.current) {
      started.current = true;
      void start(autoStart);
    }
  }, [autoStart, start]);

  const decide = useCallback(
    async (approvalId: string, decision: "approved" | "denied", note?: string) => {
      const runId = state.run?.id;
      if (!runId) return;
      setBusy(true);
      setError(null);
      try {
        const res = await fetch(`/api/runs/${runId}/approvals`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ approvalId, state: decision, note }),
        });
        if (!res.ok) throw new Error(`The approval was not recorded (${res.status}).`);
        const { run } = (await res.json()) as { run: Run };
        setState((s) => ({ ...s, approvals: run.approvals, audit: run.audit, run }));
      } catch (e) {
        setError({
          what: "That decision was not recorded.",
          detail: `${e instanceof Error ? e.message : String(e)} Nothing was executed — the action is still held.`,
        });
      } finally {
        setBusy(false);
      }
    },
    [state.run?.id],
  );

  const execute = useCallback(async () => {
    const runId = state.run?.id;
    if (!runId) return;
    setPhase("executing");
    setError(null);
    try {
      const res = await fetch(`/api/runs/${runId}/execute`, { method: "POST" });
      if (!res.ok) throw new Error(`The executor returned ${res.status}.`);
      await consume(res, apply);
      setPhase("done");
      router.refresh();
    } catch (e) {
      setError({
        what: "Execution stopped part-way.",
        detail: `${e instanceof Error ? e.message : String(e)} Completed actions are idempotent — running again will not duplicate them.`,
      });
      setPhase("ready");
    }
  }, [state.run?.id, apply, router]);

  const { capsule, run } = state;
  const pendingApprovals = state.approvals.filter((a) => a.state === "pending").length;
  const canExecute = phase === "ready" && state.approvals.length > 0 && pendingApprovals === 0;
  const noApprovalsNeeded = phase === "ready" && state.approvals.length === 0;

  const m = run?.metrics;
  const completed = state.executions.filter((e) => e.status === "succeeded").length;
  const blocked = state.plan?.actions.filter((a) => a.blockedBy).length ?? 0;

  return (
    <div className="flex min-h-dvh flex-col">
      {/* ─────────────────────────── header ─────────────────────────── */}
      <header className="sticky top-0 z-20 border-b border-line bg-ink/85 px-6 py-3.5 backdrop-blur">
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between md:gap-6">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <Signal tone={phase === "assembling" || phase === "executing" ? "live" : statusTone(run?.status ?? "idle")} />
              <span className="eyebrow">{run?.id ?? "assembling"}</span>
              {run && <Badge tone={statusTone(run.status) === "clear" ? "clear" : statusTone(run.status) === "stop" ? "stop" : "caution"}>{run.status.replace("_", " ")}</Badge>}
            </div>
            <h1 className="mt-1.5 max-w-3xl font-display text-[17px] font-semibold leading-snug tracking-tight text-text">
              {autoStart?.request ?? run?.request ?? "…"}
            </h1>
          </div>

          <div className="flex w-full flex-wrap items-center gap-2 md:w-auto md:shrink-0">
            {pendingApprovals > 0 && (
              <span className="inline-flex items-center gap-1.5 rounded-md border border-caution/35 bg-caution/10 px-2.5 py-1.5 font-mono text-[10.5px] uppercase tracking-[0.1em] text-caution">
                <ShieldCheck className="size-3.5" strokeWidth={2} />
                {pendingApprovals} awaiting you
              </span>
            )}
            {(canExecute || noApprovalsNeeded) && (
              <Button onClick={execute}>
                <Play className="size-3.5" /> Execute approved actions
              </Button>
            )}
            {state.run?.id && (
              <Button variant="outline" onClick={() => router.push(`/runs/${state.run!.id}/receipt`)}>
                <FileText className="size-3.5" /> Governed receipt
              </Button>
            )}
            {phase === "done" && (
              <Button variant="outline" onClick={() => router.push("/request")}>
                <Rewind className="size-3.5" /> New request
              </Button>
            )}
          </div>
        </div>

        {/* impact strip */}
        <StatStrip className="mt-3 grid-cols-2 sm:grid-cols-3 lg:grid-cols-6">
          <Stat label="systems touched" value={m?.sources_touched ?? new Set(state.evidence.map((e) => e.system)).size} hint="live connectors" />
          <Stat label="evidence" value={state.evidence.length} hint="cited sources" />
          <Stat label="actions" value={`${completed}/${state.plan?.actions.length ?? 0}`} hint="executed / planned" />
          <Stat label="blocked by policy" value={blocked} tone={blocked ? "stop" : "text"} hint="violations prevented" />
          <Stat label="handoffs" value={state.handoffs.length} tone="rail" hint="context preserved" />
          <Stat label="time saved" value={m?.minutes_saved ?? state.plan?.estimated_minutes_saved ?? 0} unit="min" hint="vs manual path" />
        </StatStrip>
      </header>

      {error && (
        <div role="alert" className="mx-6 mt-4 rounded-lg border border-stop/40 bg-stop/[0.06] px-4 py-3">
          <div className="flex items-start gap-2.5">
            <TriangleAlert className="mt-[2px] size-4 shrink-0 text-stop" strokeWidth={2} aria-hidden />
            <div className="min-w-0 flex-1">
              <p className="text-[13px] font-semibold text-text">{error.what}</p>
              <p className="mt-0.5 text-[12px] leading-relaxed text-muted">{error.detail}</p>
            </div>
            <Button size="sm" variant="outline" onClick={() => setError(null)}>
              Dismiss
            </Button>
          </div>
        </div>
      )}

      {/* ─────────────────────────── body ─────────────────────────── */}
      <div className="grid flex-1 grid-cols-1 gap-6 px-6 py-6 lg:grid-cols-[228px_minmax(0,1fr)]">
        <aside className="lg:sticky lg:top-[188px] lg:self-start">
          <div className="eyebrow mb-3">orchestration</div>
          <StageRail state={state.stages} />
        </aside>

        <div className="min-w-0">
          <Tabs value={tab} onValueChange={setTab}>
            <TabsList className="-mx-1 flex-wrap">
              <TabsTrigger value="capsule">Capsule</TabsTrigger>
              <TabsTrigger value="evidence">Evidence {state.evidence.length > 0 && `· ${state.evidence.length}`}</TabsTrigger>
              <TabsTrigger value="policy">Policy {state.policies.length > 0 && `· ${state.policies.length}`}</TabsTrigger>
              <TabsTrigger value="plan">Plan {state.plan && `· ${state.plan.actions.length}`}</TabsTrigger>
              <TabsTrigger value="handoff">Handoff {state.handoffs.length > 0 && `· ${state.handoffs.length}`}</TabsTrigger>
              <TabsTrigger value="approvals" className={cn(pendingApprovals > 0 && "text-caution")}>
                Approvals {pendingApprovals > 0 && `· ${pendingApprovals}`}
              </TabsTrigger>
              <TabsTrigger value="execution">Execution {state.executions.length > 0 && `· ${state.executions.length}`}</TabsTrigger>
              <TabsTrigger value="audit">Audit {state.audit.length > 0 && `· ${state.audit.length}`}</TabsTrigger>
              <TabsTrigger value="adversary" className="text-caution">Attack it</TabsTrigger>
            </TabsList>

            <div className="pt-4">
              <TabsContent value="capsule">
                {capsule ? <CapsuleView capsule={capsule} /> : <Empty>Compiling the capsule…</Empty>}
              </TabsContent>

              <TabsContent value="evidence">
                {state.evidence.length === 0 ? (
                  <Empty>Sweeping connected knowledge sources…</Empty>
                ) : (
                  <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-3">
                    {state.evidence.map((e) => (
                      <EvidenceCard key={e.id} e={e} />
                    ))}
                  </div>
                )}
              </TabsContent>

              <TabsContent value="policy">
                <PolicyList decisions={state.policies} />
              </TabsContent>

              <TabsContent value="plan">
                <PlanTable plan={state.plan} />
              </TabsContent>

              <TabsContent value="handoff">
                <HandoffGraph handoffs={state.handoffs} plan={state.plan} />
                <IntegritySeal capsule={capsule} handoffs={state.handoffs} />
                <HandoffLedger handoffs={state.handoffs} />
              </TabsContent>

              <TabsContent value="approvals">
                <ApprovalQueue approvals={state.approvals} policies={state.policies} onDecide={decide} busy={busy} />
              </TabsContent>

              <TabsContent value="execution">
                <ExecutionTimeline records={state.executions} />
              </TabsContent>

              <TabsContent value="audit">
                <AuditLog decisions={state.audit} />
              </TabsContent>

              <TabsContent value="adversary">
                <AdversaryConsole runId={state.run?.id ?? null} ready={Boolean(capsule && state.plan)} />
              </TabsContent>
            </div>
          </Tabs>
        </div>
      </div>
    </div>
  );
}

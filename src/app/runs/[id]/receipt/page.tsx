import { notFound } from "next/navigation";
import Link from "next/link";
import { getRun } from "@/lib/contextrail/store";
import { attest, verifyChain } from "@/lib/contextrail/attestation";

export const dynamic = "force-dynamic";

/* ------------------------------------------------------------------ *
 * The governed receipt.
 *
 * The manager's actual job after the run is to explain the outcome to
 * somebody who was not there — usually Security. This is that one page:
 * what was asked, what happened, what was refused and under which
 * clause, sealed with the capsule digest. Printable, and it does not
 * require reconstructing a chat log.
 * ------------------------------------------------------------------ */

const fmt = (iso: string) =>
  new Date(iso).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" });

export default async function ReceiptPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const run = getRun(id);
  if (!run) notFound();

  const subject = run.capsule.subject as Record<string, string>;
  const denied = run.plan.actions.filter((a) => a.blockedBy);
  const executed = run.executions.filter((e) => e.status === "succeeded");
  const verified = executed.filter((e) => e.verified);
  const held = run.plan.actions.filter((a) => a.approvalRequired && !a.blockedBy);
  const decisions = run.policies;
  const chain = attest(run);
  const chainVerdict = verifyChain(run);

  return (
    <main className="mx-auto max-w-[860px] px-6 py-10 print:py-0">
      <div className="mb-6 flex items-center justify-between gap-3 print:hidden">
        <Link href={`/runs/${run.id}`} className="font-mono text-[11px] text-rail hover:underline">
          ← back to the run
        </Link>
        <span className="font-mono text-[10px] uppercase tracking-wider text-dim">
          printable · Ctrl/Cmd + P
        </span>
      </div>

      <article className="border border-line bg-panel">
        {/* ── header ── */}
        <header className="border-b border-line px-7 py-6">
          <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-dim">
            Governed outcome · {run.tenant_id} · {run.id}
          </p>
          <h1 className="mt-2 font-display text-2xl font-bold tracking-tight">
            {executed.length === 0 ? (
              <>
                Plan governed and sealed. Nothing executed yet.
                {denied.length > 0 && ` ${denied.length} action refused outright.`}
              </>
            ) : (
              <>
                {verified.length} of {run.plan.actions.length} actions completed and verified.
                {denied.length > 0 && ` ${denied.length} refused.`}
              </>
            )}
          </h1>
          <p className="mt-2 max-w-[68ch] text-sm text-muted">“{run.request}”</p>
          <p className="mt-3 font-mono text-[11px] text-dim">
            Requested by {run.capsule.requester.name}, {run.capsule.requester.role} ·{" "}
            {fmt(run.createdAt)}
          </p>
        </header>

        {/* ── subject ── */}
        <section className="border-b border-line px-7 py-5">
          <h2 className="mb-2 font-mono text-[10px] uppercase tracking-[0.14em] text-dim">
            Subject — resolved by identity, not by search
          </h2>
          <p className="text-sm">
            <span className="font-semibold">{subject.name}</span>{" "}
            <span className="font-mono text-xs text-muted">
              {subject.worker_id} · {subject.employment_type}
              {subject.start_date && ` · starts ${subject.start_date}`}
              {subject.engagement_ends && ` · engagement ends ${subject.engagement_ends}`}
            </span>
          </p>
        </section>

        {/* ── the refusal, first, because it is the thing being explained ── */}
        {denied.length > 0 && (
          <section className="border-b border-line bg-stop/5 px-7 py-5">
            <h2 className="mb-3 font-mono text-[10px] uppercase tracking-[0.14em] text-stop">
              Refused — terminal, not queued
            </h2>
            {denied.map((a) => {
              const d = decisions.find((p) => p.policyId === a.blockedBy);
              return (
                <div key={a.id} className="space-y-1.5">
                  <p className="text-sm font-semibold">{a.title}</p>
                  <p className="font-mono text-[11px] text-stop">
                    {a.blockedBy} · never executed
                  </p>
                  {d?.reason && <p className="max-w-[70ch] text-sm text-muted">{d.reason}</p>}
                </div>
              );
            })}
          </section>
        )}

        {/* ── what was done ── */}
        <section className="border-b border-line px-7 py-5">
          <h2 className="mb-3 font-mono text-[10px] uppercase tracking-[0.14em] text-dim">
            Completed — each confirmed by a post-condition probe
          </h2>
          <ul className="space-y-2">
            {executed.map((e) => (
              <li key={e.actionId} className="flex flex-wrap items-baseline gap-x-2 text-sm">
                <span className="font-mono text-[11px] text-dim">{e.actionId}</span>
                <span className="font-mono text-[11px] text-text/90">{e.tool}</span>
                {e.attempts > 1 && (
                  <span className="font-mono text-[10px] text-caution">{e.attempts} attempts</span>
                )}
                <span className={e.verified ? "font-mono text-[10px] text-clear" : "font-mono text-[10px] text-caution"}>
                  {e.verified ? "verified" : "unverified"}
                </span>
                {e.verification_note && (
                  <span className="w-full text-xs text-muted">{e.verification_note}</span>
                )}
              </li>
            ))}
            {executed.length === 0 && (
              <li className="text-xs text-muted">
                Nothing executed yet — {held.length > 0 ? `${held.length} privileged action awaiting a named human.` : "approve the plan to execute."}
              </li>
            )}
          </ul>
        </section>

        {/* ── human decisions ── */}
        {run.approvals.length > 0 && (
          <section className="border-b border-line px-7 py-5">
            <h2 className="mb-3 font-mono text-[10px] uppercase tracking-[0.14em] text-dim">
              Privileged actions — held for a named human
            </h2>
            <ul className="space-y-2">
              {run.approvals.map((a) => (
                <li key={a.id} className="text-sm">
                  <span className="font-semibold">{a.title}</span>{" "}
                  <span className="font-mono text-[11px] text-muted">
                    {a.state} · {a.approver}
                    {a.decidedAt && ` · ${fmt(a.decidedAt)}`}
                  </span>
                  {a.note && <p className="text-xs text-muted">Reason given: “{a.note}”</p>}
                </li>
              ))}
            </ul>
            {held.length > 0 && run.approvals.length === 0 && (
              <p className="text-xs text-muted">{held.length} awaiting a decision.</p>
            )}
          </section>
        )}

        {/* ── attestation ── */}
        <section className="border-b border-line px-7 py-5">
          <h2 className="mb-2 font-mono text-[10px] uppercase tracking-[0.14em] text-dim">
            Attestation — tamper-evident decision log
          </h2>
          <p className="max-w-[70ch] text-xs text-muted">
            {chainVerdict.entries} decisions, hash-chained in order. EU AI Act Article 12
            requires high-risk systems to keep automatically recorded, tamper-evident logs and to
            distinguish an intervention that stops an action from one that merely warns. Editing
            or removing any entry below breaks every link after it.
          </p>
          <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 font-mono text-[11px]">
            <span className={chainVerdict.ok ? "text-clear" : "text-stop"}>
              chain {chainVerdict.ok ? "intact" : `broken at #${chainVerdict.brokenAt}`}
            </span>
            <span className="text-stop">hard gates: {chainVerdict.hardGates}</span>
            <span className="text-caution">soft gates: {chainVerdict.softGates}</span>
            <span className="text-dim">head sha256:{chainVerdict.head}</span>
          </div>
          <ol className="mt-3 space-y-1">
            {chain.map((e) => (
              <li key={e.seq} className="flex flex-wrap items-baseline gap-x-2 font-mono text-[10px]">
                <span className="text-dim">#{String(e.seq).padStart(2, "0")}</span>
                <span
                  className={
                    e.gate === "hard" ? "text-stop" : e.gate === "soft" ? "text-caution" : "text-dim"
                  }
                >
                  {e.gate}
                </span>
                <span className="text-text/80">{e.actor}</span>
                <span className="min-w-0 flex-1 truncate text-muted">{e.summary}</span>
                <span className="text-dim">{e.hash.slice(0, 8)}</span>
              </li>
            ))}
          </ol>
        </section>

        {/* ── the seal ── */}
        <footer className="px-7 py-5">
          <h2 className="mb-2 font-mono text-[10px] uppercase tracking-[0.14em] text-dim">
            Seal
          </h2>
          <p className="max-w-[70ch] text-xs text-muted">
            The capsule digest covers the subject, {run.capsule.constraints.length} constraints,
            every recorded decision and {run.capsule.open_blockers.length} open blocker
            {run.capsule.open_blockers.length === 1 ? "" : "s"}. Recomputing it on any receiving
            system proves this record was not edited after the fact.
          </p>
          <code className="mt-2 block font-mono text-[11px] text-clear">
            sha256:{run.capsule.capsule_digest ?? "—"}
          </code>
          <p className="mt-3 font-mono text-[10px] text-dim">
            Evidence: {run.capsule.sources.length} cited sources · Handoffs:{" "}
            {run.capsule.handoff_chain.join(" → ")} · Status: {run.status}
          </p>
        </footer>
      </article>

      <p className="mt-4 font-mono text-[10px] text-dim print:hidden">
        Fixture tenant. Connectors are demo fixtures, not live systems.
      </p>
    </main>
  );
}

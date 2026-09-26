import Link from "next/link";
import { ArrowRight, Plus } from "lucide-react";
import { listRuns } from "@/lib/contextrail/store";

export const dynamic = "force-dynamic";

function label(status: string) {
  if (status === "awaiting_approval") return "Needs approval";
  if (status === "complete") return "Done";
  if (status === "partial") return "Partly done";
  if (status === "failed") return "Needs attention";
  return "In progress";
}

export default function RequestsPage() {
  const runs = listRuns();
  return <div className="mx-auto max-w-[760px] px-5 pb-20 pt-12 md:px-8 md:pt-20">
    <div className="flex items-center justify-between gap-4">
      <div><p className="text-sm font-medium text-rail">Your activity</p><h1 className="mt-2 font-display text-4xl font-semibold tracking-tight text-text">My requests</h1></div>
      <Link href="/request" className="inline-flex h-10 items-center gap-2 rounded-lg bg-rail px-4 text-sm font-semibold text-ink"><Plus className="size-4" /> New</Link>
    </div>
    <p className="mt-3 text-sm text-muted">Requests simulated in this demo.</p>
    {runs.length === 0 ? <div className="mt-10 rounded-2xl border border-dashed border-line-strong px-6 py-12 text-center text-sm text-muted">No requests yet. Start with what you need done.</div> :
      <div className="mt-8 space-y-2">{runs.map((run) => <Link key={run.id} href={`/runs/${run.id}`} className="flex items-center gap-4 rounded-xl border border-line bg-panel px-4 py-4 hover:border-line-strong"><div className="min-w-0 flex-1"><p className="truncate text-sm font-medium text-text">{run.request.split("\n")[0]}</p><p className="mt-1 text-xs text-dim">{run.id}</p></div><span className="shrink-0 text-xs text-muted">{label(run.status)}</span><ArrowRight className="size-4 shrink-0 text-dim" /></Link>)}</div>}
  </div>;
}

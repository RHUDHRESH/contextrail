import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { RequestComposer } from "@/components/rail/request-composer";
import { listRuns } from "@/lib/contextrail/store";
import { redirect } from "next/navigation";

export const dynamic = "force-dynamic";

function stateLabel(status: string) {
  if (status === "awaiting_approval") return "Needs approval";
  if (status === "complete") return "Done";
  if (status === "partial") return "Partly done";
  if (status === "failed") return "Needs attention";
  return "In progress";
}

export default function Home() {
  if (process.env.NODE_ENV !== "production" && process.env.DEMO_ENGINE_URL) redirect("/engine-demo");
  const runs = listRuns().slice(0, 4);
  return <>
    <RequestComposer />
    {runs.length > 0 && <section className="mx-auto max-w-[760px] px-5 pb-20 md:px-8">
      <div className="flex items-center justify-between border-t border-line pt-6">
        <h2 className="font-display text-lg font-semibold text-text">Recent requests</h2>
        <Link href="/requests" className="text-sm text-rail hover:underline">See all</Link>
      </div>
      <div className="mt-4 space-y-2">{runs.map((run) => <Link href={`/runs/${run.id}`} key={run.id} className="flex items-center gap-4 rounded-xl border border-line bg-panel px-4 py-3 hover:border-line-strong">
        <span className="min-w-0 flex-1 truncate text-sm text-text">{run.request.split("\n")[0]}</span>
        <span className="shrink-0 text-xs text-muted">{stateLabel(run.status)}</span><ArrowRight className="size-4 shrink-0 text-dim" />
      </Link>)}</div>
    </section>}
  </>;
}

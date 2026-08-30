import { notFound } from "next/navigation";
import { getRun } from "@/lib/contextrail/store";
import { RunConsole } from "@/components/rail/run-console";

export const dynamic = "force-dynamic";

export default async function RunPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const run = getRun(id);
  if (!run) notFound();
  return <RunConsole initialRun={run} />;
}

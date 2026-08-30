import { z } from "zod";
import { assemble } from "@/lib/contextrail/engine";
import { listRuns } from "@/lib/contextrail/store";
import { sseResponse } from "@/lib/sse";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const Body = z.object({
  request: z.string().min(8, "Describe the request in a sentence or more."),
  requesterId: z.string().optional(),
  tenantId: z.string().optional(),
  scenarioId: z.string().nullable().optional(),
  pace: z.number().min(0).max(2000).optional(),
});

export async function POST(req: Request) {
  const parsed = Body.safeParse(await req.json().catch(() => ({})));
  if (!parsed.success) {
    return Response.json({ error: parsed.error.issues[0]?.message ?? "Invalid request" }, { status: 400 });
  }
  return sseResponse(assemble(parsed.data));
}

export async function GET() {
  return Response.json({ runs: listRuns() });
}

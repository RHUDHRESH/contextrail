import { getRun } from "@/lib/contextrail/store";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const run = getRun(id);
  if (!run) return Response.json({ error: `Run ${id} not found` }, { status: 404 });
  return Response.json({ run });
}

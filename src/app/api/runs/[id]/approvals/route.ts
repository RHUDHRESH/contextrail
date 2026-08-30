import { z } from "zod";
import { updateApproval } from "@/lib/contextrail/store";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const Body = z.object({
  approvalId: z.string(),
  state: z.enum(["approved", "denied"]),
  note: z.string().max(400).optional(),
});

export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const parsed = Body.safeParse(await req.json().catch(() => ({})));
  if (!parsed.success) {
    return Response.json({ error: parsed.error.issues[0]?.message ?? "Invalid body" }, { status: 400 });
  }
  const run = updateApproval(id, parsed.data.approvalId, parsed.data.state, parsed.data.note);
  if (!run) return Response.json({ error: `Run ${id} not found` }, { status: 404 });
  return Response.json({ run });
}

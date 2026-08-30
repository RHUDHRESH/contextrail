import { z } from "zod";
import { ATTACKS, runAttack } from "@/lib/contextrail/adversary";
import { getRun } from "@/lib/contextrail/store";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const Body = z.object({
  attack: z.enum(["forge_approval", "strip_constraint", "swap_subject", "replay_write", "injected_instruction"]),
});

/** The catalogue, so the console can render before anything is attempted. */
export async function GET() {
  return Response.json({ attacks: ATTACKS });
}

export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const parsed = Body.safeParse(await req.json().catch(() => ({})));
  if (!parsed.success) {
    return Response.json({ error: parsed.error.issues[0]?.message ?? "Invalid body" }, { status: 400 });
  }

  const run = getRun(id);
  if (!run) return Response.json({ error: `Run ${id} not found` }, { status: 404 });

  // Attacks run against a copy of the stored run and never mutate it —
  // the console proves the guarantees without corrupting the demo.
  const outcome = await runAttack(run, parsed.data.attack);
  return Response.json({ outcome });
}

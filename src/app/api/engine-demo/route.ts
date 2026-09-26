import { z } from "zod";

export const runtime = "nodejs";

const personas = {
  employee: { label: "Anil Kumar", channel: "slack", externalId: "U0ANIL001" },
  contractor: { label: "Priya Raghunathan", channel: "email", externalId: "priya.r@contractor.northbeam.example" },
  manager: { label: "Dana Osei", channel: "slack", externalId: "U0DANA050" },
} as const;
const Body = z.object({ persona: z.enum(["employee", "contractor", "manager"]), request: z.string().trim().min(8).max(1000) });
const PersonaQuery = z.enum(["employee", "contractor", "manager"]);

function localDemo(req: Request) {
  const host = new URL(req.url).hostname;
  return process.env.NODE_ENV !== "production" && (host === "localhost" || host === "127.0.0.1");
}

function config() {
  const base = process.env.DEMO_ENGINE_URL;
  const token = process.env.ENGINE_TOKEN;
  if (!base || !token || token === "change-me") return null;
  const url = new URL(base);
  if (url.protocol !== "http:" || !["127.0.0.1", "localhost"].includes(url.hostname)) return null;
  return { base: url.origin, token };
}

async function engineFetch(target: NonNullable<ReturnType<typeof config>>, path: string, init?: RequestInit) {
  return fetch(`${target.base}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${target.token}`, ...init?.headers },
    signal: init?.signal ?? AbortSignal.timeout(60000),
    cache: "no-store",
  });
}

export async function GET(req: Request) {
  if (!localDemo(req)) return Response.json({ available: false }, { status: 404 });
  const target = config();
  if (!target) return Response.json({ available: false });
  const persona = PersonaQuery.safeParse(new URL(req.url).searchParams.get("persona") ?? "");
  try {
    if (!persona.success) {
      const response = await engineFetch(target, "/health", { signal: AbortSignal.timeout(3000) });
      return Response.json({ available: response.ok });
    }
    const actor = personas[persona.data];
    const body = JSON.stringify({ channel: actor.channel, actor_external_id: actor.externalId });
    const [historyResponse, pendingResponse] = await Promise.all([
      engineFetch(target, "/v1/runs/mine", { method: "POST", body }),
      persona.data === "manager" ? engineFetch(target, "/v1/approvals/pending", { method: "POST", body }) : null,
    ]);
    if (!historyResponse.ok || (pendingResponse && !pendingResponse.ok)) return Response.json({ error: `Engine returned ${(!historyResponse.ok ? historyResponse : pendingResponse)!.status}.` }, { status: 502 });
    const history = await historyResponse.json();
    const pending = pendingResponse ? await pendingResponse.json() : { runs: [] };
    return Response.json({ available: true, runs: history.runs, pending: pending.runs });
  } catch {
    return Response.json({ error: "Could not reach the local engine." }, { status: 502 });
  }
}

export async function POST(req: Request) {
  if (!localDemo(req)) return Response.json({ error: "Local demo only." }, { status: 404 });
  const target = config();
  if (!target) return Response.json({ error: "Local engine demo is not configured." }, { status: 503 });
  const parsed = Body.safeParse(await req.json().catch(() => null));
  if (!parsed.success) return Response.json({ error: "Choose a demo persona and describe the request in one sentence." }, { status: 400 });
  const actor = personas[parsed.data.persona];
  try {
    const response = await engineFetch(target, "/v1/runs", {
      method: "POST",
      body: JSON.stringify({ request_text: parsed.data.request, channel: actor.channel, actor_external_id: actor.externalId }),
    });
    if (!response.ok) return Response.json({ error: `Engine returned ${response.status}.` }, { status: 502 });
    return Response.json(await response.json(), { status: 201 });
  } catch {
    return Response.json({ error: "Could not reach the local engine." }, { status: 502 });
  }
}

export async function PATCH(req: Request) {
  if (!localDemo(req)) return Response.json({ error: "Local demo only." }, { status: 404 });
  const target = config();
  if (!target) return Response.json({ error: "Local engine demo is not configured." }, { status: 503 });
  const body = z.object({ persona: z.literal("manager"), run_id: z.string().uuid(), action_id: z.string().min(1), params_hash: z.string().regex(/^[0-9a-f]{64}$/), decision: z.enum(["approved", "refused"]), reason: z.string().max(1000).optional() }).safeParse(await req.json().catch(() => null));
  if (!body.success) return Response.json({ error: "Invalid approval decision." }, { status: 400 });
  const actor = personas.manager;
  try {
    const response = await engineFetch(target, `/v1/runs/${body.data.run_id}/decisions`, {
      method: "POST",
      body: JSON.stringify({ action_id: body.data.action_id, params_hash: body.data.params_hash, channel: actor.channel, actor_external_id: actor.externalId, decision: body.data.decision, reason: body.data.reason }),
    });
    if (!response.ok) return Response.json({ error: `Engine returned ${response.status}.` }, { status: 502 });
    return Response.json(await response.json());
  } catch {
    return Response.json({ error: "Could not reach the local engine." }, { status: 502 });
  }
}

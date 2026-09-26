import { z } from "zod";

export const runtime = "nodejs";

const Body = z.object({ request: z.string().trim().min(8).max(1000) });

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

export async function GET(req: Request) {
  if (!localDemo(req)) return Response.json({ available: false }, { status: 404 });
  const target = config();
  if (!target) return Response.json({ available: false });
  try {
    const response = await fetch(`${target.base}/health`, { signal: AbortSignal.timeout(3000), cache: "no-store" });
    return Response.json({ available: response.ok });
  } catch {
    return Response.json({ available: false });
  }
}

export async function POST(req: Request) {
  if (!localDemo(req)) return Response.json({ error: "Local demo only." }, { status: 404 });
  const target = config();
  if (!target) return Response.json({ error: "Local engine demo is not configured." }, { status: 503 });
  const parsed = Body.safeParse(await req.json().catch(() => null));
  if (!parsed.success) return Response.json({ error: "Describe the request in one sentence." }, { status: 400 });
  try {
    const response = await fetch(`${target.base}/v1/runs`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${target.token}` },
      body: JSON.stringify({ request_text: parsed.data.request, channel: "mcp", actor_external_id: "p-anil" }),
      signal: AbortSignal.timeout(60000),
      cache: "no-store",
    });
    if (!response.ok) return Response.json({ error: `Engine returned ${response.status}.` }, { status: 502 });
    return Response.json(await response.json(), { status: 201 });
  } catch {
    return Response.json({ error: "Could not reach the local engine." }, { status: 502 });
  }
}

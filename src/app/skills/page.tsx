import { Boxes, Terminal } from "lucide-react";
import { MCP_TOOLS, SKILLS } from "@/lib/contextrail/catalog";
import { Badge } from "@/components/ui/badge";
import { Stat, StatStrip } from "@/components/rail/metrics";

export const metadata = { title: "Skills & Tools — ContextRail" };

export default function SkillsPage() {
  return (
    <div className="mx-auto max-w-[1060px] px-6 py-8">
      <header>
        <div className="eyebrow">platform surface</div>
        <h1 className="mt-1.5 font-display text-[26px] font-semibold leading-tight tracking-tight text-text">
          Skills &amp; Tools
        </h1>
        <p className="mt-1 max-w-2xl text-[13px] leading-relaxed text-muted">
          ContextRail is infrastructure, not a closed app. Everything in the demo is reachable from Freshworks Agent
          Studio or any standards-compatible MCP client through six tools and five installable skills.
        </p>
      </header>

      <StatStrip className="mt-6 grid-cols-3">
        <Stat label="mcp tools" value={MCP_TOOLS.length} tone="rail" hint="zod-validated boundaries" />
        <Stat label="skills" value={SKILLS.length} tone="clear" hint="installable, composable" />
        <Stat label="connectors" value={8} hint="Freshservice + 7 mocked" />
      </StatStrip>

      {/* ── skills ── */}
      <section className="mt-8">
        <div className="flex items-baseline justify-between border-b border-line pb-2">
          <h2 className="flex items-center gap-2 font-display text-[13px] font-semibold tracking-tight text-text">
            <Boxes className="size-3.5 text-clear" strokeWidth={2} /> Skill pack
          </h2>
          <span className="eyebrow">install one, or the rail</span>
        </div>

        <div className="mt-3 grid gap-2.5 md:grid-cols-2">
          {SKILLS.map((s) => (
            <article key={s.name} className="panel-raised flex flex-col p-4">
              <div className="flex items-center justify-between gap-2">
                <code className="font-mono text-[11.5px] text-clear">{s.name}</code>
                <Badge tone="neutral">{s.stage}</Badge>
              </div>

              <p className="mt-2 flex-1 text-[12px] leading-relaxed text-muted">{s.blurb}</p>

              <dl className="mt-3 space-y-1.5 border-t border-line pt-2.5">
                <Field label="in" value={s.inputs} />
                <Field label="out" value={s.outputs} />
              </dl>

              <div className="mt-2.5 flex flex-wrap gap-1">
                {s.uses.map((t) => (
                  <code key={t} className="rounded bg-panel-3 px-1.5 py-px font-mono text-[9.5px] text-rail">
                    {t}
                  </code>
                ))}
              </div>

              <div className="mt-2 flex flex-wrap gap-1">
                {s.integrations.map((i) => (
                  <span key={i} className="rounded border border-line-strong px-1.5 py-px font-mono text-[9.5px] text-dim">
                    {i}
                  </span>
                ))}
              </div>
            </article>
          ))}
        </div>
      </section>

      {/* ── tools ── */}
      <section className="mt-9">
        <div className="flex items-baseline justify-between border-b border-line pb-2">
          <h2 className="flex items-center gap-2 font-display text-[13px] font-semibold tracking-tight text-text">
            <Terminal className="size-3.5 text-rail" strokeWidth={2} /> MCP tools
          </h2>
          <span className="eyebrow">stdio · npm run mcp</span>
        </div>

        <div className="mt-3 space-y-2.5">
          {MCP_TOOLS.map((t) => (
            <article key={t.name} className="panel p-4">
              <div className="flex flex-wrap items-center gap-2">
                <code className="font-mono text-[12.5px] font-medium text-rail">{t.name}</code>
                <Badge tone="neutral">{t.stage}</Badge>
              </div>

              <p className="mt-1.5 max-w-3xl text-[12px] leading-relaxed text-muted">{t.summary}</p>

              <div className="mt-3 grid gap-3 md:grid-cols-2">
                <Schema title="input" rows={t.input} />
                <Schema title="output" rows={t.output} />
              </div>

              <div className="mt-3 grid gap-2 border-t border-line pt-2.5 md:grid-cols-2">
                <div>
                  <div className="eyebrow">access boundary</div>
                  <p className="mt-1 text-[11.5px] leading-relaxed text-muted">{t.boundary}</p>
                </div>
                <div>
                  <div className="eyebrow">errors</div>
                  <ul className="mt-1 space-y-0.5">
                    {t.errors.map((e) => (
                      <li key={e} className="font-mono text-[10.5px] leading-relaxed text-caution">
                        {e}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </article>
          ))}
        </div>
      </section>

      {/* ── wiring ── */}
      <section className="mt-9">
        <h2 className="border-b border-line pb-2 font-display text-[13px] font-semibold tracking-tight text-text">
          Wire it into any MCP client
        </h2>
        <pre className="mt-3 overflow-x-auto rounded-lg border border-line bg-ink/60 p-4 font-mono text-[11px] leading-relaxed text-muted">
{`{
  "mcpServers": {
    "contextrail": {
      "command": "npx",
      "args": ["tsx", "mcp/server.ts"],
      "env": { "CONTEXTRAIL_TENANT": "acme-corp" }
    }
  }
}`}
        </pre>
      </section>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[28px_1fr] gap-2">
      <dt className="eyebrow pt-px">{label}</dt>
      <dd className="text-[11.5px] leading-relaxed text-muted">{value}</dd>
    </div>
  );
}

function Schema({ title, rows }: { title: string; rows: Record<string, string> }) {
  return (
    <div className="rounded-lg border border-line bg-panel-2/40 p-2.5">
      <div className="eyebrow">{title}</div>
      <dl className="mt-1.5 space-y-1">
        {Object.entries(rows).map(([k, v]) => (
          <div key={k}>
            <dt className="font-mono text-[10.5px] text-text">{k}</dt>
            <dd className="font-mono text-[10px] leading-relaxed text-dim">{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

import type { Decision } from "@/lib/contextrail/types";
import { clock } from "@/lib/utils";
import { Empty } from "./policy-list";

const KIND_TONE: Record<string, string> = {
  intent_resolved: "text-rail",
  policy_evaluated: "text-caution",
  plan_generated: "text-rail",
  handoff: "text-notion",
  approval_granted: "text-clear",
  approval_denied: "text-stop",
  action_executed: "text-clear",
  action_blocked: "text-stop",
  verification: "text-freshservice",
};

/** Immutable, append-only. This is the artefact a compliance reviewer reads. */
export function AuditLog({ decisions }: { decisions: Decision[] }) {
  if (!decisions.length) return <Empty>The audit trail is empty.</Empty>;

  return (
    <ol className="space-y-px font-mono text-[11px]">
      {decisions.map((d) => (
        <li key={d.id} className="grid grid-cols-[68px_128px_1fr] gap-2 rounded px-2 py-1.5 hover:bg-panel-2/60">
          <span className="tabular text-dim">{clock(d.at)}</span>
          <span className={`truncate ${KIND_TONE[d.kind] ?? "text-muted"}`}>{d.kind}</span>
          <span className="min-w-0 leading-relaxed text-muted">
            <span className="text-dim">{d.actor}</span> {d.summary}
          </span>
        </li>
      ))}
    </ol>
  );
}

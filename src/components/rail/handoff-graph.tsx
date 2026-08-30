"use client";

import { useMemo } from "react";
import { Background, Handle, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { AGENTS } from "@/lib/contextrail/agents";
import type { ActionPlan, AgentId } from "@/lib/contextrail/types";
import { AGENT_COLOR } from "@/lib/utils";
import { Empty } from "./policy-list";

export type HandoffEvent = { from: AgentId | "ORCHESTRATOR"; to: AgentId; carries: string[] };

type NodeData = { title: string; sub: string; accent: string; actions: string[]; entry?: boolean };
type AgentFlowNode = Node<NodeData, "agent">;

function AgentNode({ data }: NodeProps<AgentFlowNode>) {
  return (
    <div
      className="w-[212px] rounded-lg border bg-panel-2 px-3 py-2.5 shadow-lg shadow-black/40"
      style={{ borderColor: `color-mix(in oklab, ${data.accent} 45%, transparent)` }}
    >
      <Handle type="target" position={Position.Left} />
      <div className="flex items-center gap-2">
        <span className="size-2 shrink-0 rounded-full" style={{ background: data.accent }} />
        <span className="truncate text-[12px] font-semibold tracking-tight text-text">{data.title}</span>
      </div>
      <div className="eyebrow mt-1">{data.sub}</div>
      {data.actions.length > 0 && (
        <ul className="mt-2 space-y-0.5 border-t border-line pt-2">
          {data.actions.slice(0, 3).map((a, i) => (
            <li key={i} className="truncate text-[10.5px] leading-snug text-muted">
              · {a}
            </li>
          ))}
          {data.actions.length > 3 && (
            <li className="text-[10.5px] text-dim">+{data.actions.length - 3} more</li>
          )}
        </ul>
      )}
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

const NODE_TYPES = { agent: AgentNode };

/**
 * The routing picture. Edge labels say what actually travelled — the
 * claim "handoff carries context" is only credible if you can see the cargo.
 */
export function HandoffGraph({ handoffs, plan }: { handoffs: HandoffEvent[]; plan: ActionPlan | null }) {
  const { nodes, edges } = useMemo(() => {
    if (!handoffs.length) return { nodes: [] as AgentFlowNode[], edges: [] as Edge[] };

    const nodes: AgentFlowNode[] = [
      {
        id: "ORCHESTRATOR",
        type: "agent",
        position: { x: 0, y: 0 },
        data: { title: "ContextRail", sub: "orchestrator", accent: "var(--color-rail)", actions: [], entry: true },
      },
    ];

    handoffs.forEach((h, i) => {
      const def = AGENTS[h.to];
      const owned = (plan?.actions ?? []).filter((a) => a.agent === h.to && !a.blockedBy).map((a) => a.title);
      nodes.push({
        id: h.to,
        type: "agent",
        position: { x: (i + 1) * 300, y: 0 },
        data: { title: def.name, sub: def.owner, accent: AGENT_COLOR[h.to], actions: owned },
      });
    });

    const edges: Edge[] = handoffs.map((h, i) => ({
      id: `e${i}`,
      source: h.from,
      target: h.to,
      animated: true,
      // Keep the edge readable; the full manifest is in the ledger below.
      label: `${h.carries.find((c) => c.includes('assigned')) ?? 'capsule'} + full capsule`,
      labelBgPadding: [6, 3],
      labelBgBorderRadius: 4,
      labelBgStyle: { fill: "var(--color-panel-3)", fillOpacity: 0.95 },
      labelStyle: { fill: "var(--color-muted)", fontSize: 10, fontFamily: "var(--font-mono)" },
      style: { stroke: "var(--color-rail-dim)" },
    }));

    return { nodes, edges };
  }, [handoffs, plan]);

  if (!handoffs.length) return <Empty>No handoffs yet — the capsule is still with the orchestrator.</Empty>;

  return (
    <div className="h-[300px] overflow-hidden rounded-lg border border-line bg-panel-2/40">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        fitView
        fitViewOptions={{ padding: 0.12 }}
        proOptions={{ hideAttribution: true }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        zoomOnScroll={false}
        panOnScroll
      >
        <Background gap={22} size={1} color="var(--color-line)" />
      </ReactFlow>
    </div>
  );
}

/** Text ledger of the same data — what each agent received, in full. */
export function HandoffLedger({ handoffs }: { handoffs: HandoffEvent[] }) {
  if (!handoffs.length) return null;
  return (
    <ul className="mt-3 space-y-2">
      {handoffs.map((h, i) => (
        <li key={i} className="rounded-lg border border-line bg-panel-2/50 p-3">
          <div className="flex items-center gap-2 font-mono text-[10.5px]">
            <span className="text-dim">{h.from}</span>
            <span className="text-rail">→</span>
            <span style={{ color: AGENT_COLOR[h.to] }}>{h.to}</span>
          </div>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {h.carries.map((c, j) => (
              <span key={j} className="rounded border border-line-strong bg-panel px-1.5 py-0.5 font-mono text-[10px] text-muted">
                {c}
              </span>
            ))}
          </div>
        </li>
      ))}
    </ul>
  );
}

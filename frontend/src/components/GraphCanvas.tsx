"use client";
import { useMemo } from "react";
import {
  Background,
  Controls,
  ReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useGraphStore } from "@/store/graphStore";
import { ConceptNode } from "./ConceptNode";

const nodeTypes = { concept: ConceptNode };

// Deterministic layout: spine nodes form a central vertical path; lateral web
// nodes fan out to the right. No layout lib needed for Phase 4.
function layout(order: string[], onSpine: (id: string) => boolean) {
  const pos: Record<string, { x: number; y: number }> = {};
  let spineRow = 0;
  let lateralRow = 0;
  for (const id of order) {
    if (onSpine(id)) {
      pos[id] = { x: 0, y: spineRow * 130 };
      spineRow++;
    } else {
      pos[id] = { x: 320, y: lateralRow * 110 };
      lateralRow++;
    }
  }
  return pos;
}

export function GraphCanvas() {
  const nodes = useGraphStore((s) => s.nodes);
  const edges = useGraphStore((s) => s.edges);
  const order = useGraphStore((s) => s.order);
  const selectedId = useGraphStore((s) => s.selectedId);
  const select = useGraphStore((s) => s.select);

  const rfNodes = useMemo<Node[]>(() => {
    const pos = layout(order, (id) => nodes[id]?.onSpine ?? false);
    return order
      .filter((id) => nodes[id])
      .map((id) => {
        const n = nodes[id];
        return {
          id,
          type: "concept",
          position: pos[id] ?? { x: 0, y: 0 },
          data: {
            title: n.title,
            kind: n.kind,
            onSpine: n.onSpine,
            optimistic: n.optimistic,
            flagged: n.flagged,
            selected: id === selectedId,
          },
        };
      });
  }, [nodes, order, selectedId]);

  const rfEdges = useMemo<Edge[]>(
    () =>
      Object.values(edges)
        .filter((e) => nodes[e.source] && nodes[e.target])
        .map((e) => ({
          id: e.id,
          source: e.source,
          target: e.target,
          animated: e.type === "next_in_spine",
          label: e.type,
        })),
    [edges, nodes],
  );

  return (
    <div className="h-full w-full">
      <ReactFlow
        nodes={rfNodes}
        edges={rfEdges}
        nodeTypes={nodeTypes}
        onNodeClick={(_, node) => select(node.id)}
        onPaneClick={() => select(null)}
        fitView
        proOptions={{ hideAttribution: true }}
      >
        <Background />
        <Controls />
      </ReactFlow>
    </div>
  );
}

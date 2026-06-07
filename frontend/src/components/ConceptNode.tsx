"use client";
import { Handle, Position, type NodeProps } from "@xyflow/react";

export interface ConceptNodeData {
  title: string;
  onSpine: boolean;
  optimistic: boolean;
  flagged?: boolean;
  selected?: boolean;
  [key: string]: unknown;
}

/** A graph node. Spine nodes are accented; lateral web nodes are faded;
 *  optimistic (not-yet-canonical) nodes pulse; low-confidence nodes are warned. */
export function ConceptNode({ data }: NodeProps) {
  const d = data as ConceptNodeData;
  const ring = d.selected ? "ring-2 ring-accent" : "ring-1 ring-border";
  const accent = d.onSpine ? "border-l-4 border-l-spine" : "opacity-70";
  const pulse = d.optimistic ? "animate-pulse" : "";
  return (
    <div
      className={`max-w-[200px] rounded-md border border-border bg-node-bg px-3 py-2 text-fg shadow-sm ${ring} ${accent} ${pulse}`}
    >
      <Handle type="target" position={Position.Top} className="!bg-border" />
      <div className="text-sm font-medium leading-snug">{d.title}</div>
      {d.flagged && <div className="mt-1 text-[10px] text-warn">low confidence</div>}
      <Handle type="source" position={Position.Bottom} className="!bg-border" />
    </div>
  );
}

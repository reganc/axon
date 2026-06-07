"use client";
import { Handle, Position, type NodeProps } from "@xyflow/react";

export interface ConceptNodeData {
  title: string;
  kind?: string;
  onSpine: boolean;
  optimistic: boolean;
  flagged?: boolean;
  selected?: boolean;
  [key: string]: unknown;
}

// A small glyph per node kind so types read at a glance on the canvas.
const KIND_GLYPH: Record<string, string> = {
  question: "?",
  person: "◆",
  artifact: "▤",
  project: "▣",
  skill: "✦",
  apply: "⚙",
};

/** A graph node. Spine nodes are accented; lateral web nodes are faded;
 *  optimistic (not-yet-canonical) nodes pulse; low-confidence nodes are warned;
 *  non-concept kinds (question/person/…) carry a type badge. */
export function ConceptNode({ data }: NodeProps) {
  const d = data as ConceptNodeData;
  const ring = d.selected ? "ring-2 ring-accent" : "ring-1 ring-border";
  const accent = d.onSpine ? "border-l-4 border-l-spine" : "opacity-70";
  const pulse = d.optimistic ? "animate-pulse" : "";
  const glyph = d.kind ? KIND_GLYPH[d.kind] : undefined;
  const isQuestion = d.kind === "question";
  return (
    <div
      className={`max-w-[200px] rounded-md border border-border bg-node-bg px-3 py-2 text-fg shadow-sm ${ring} ${accent} ${pulse} ${isQuestion ? "italic" : ""}`}
    >
      <Handle type="target" position={Position.Top} className="!bg-border" />
      <div className="flex items-start gap-1.5">
        {glyph && (
          <span className="mt-0.5 text-xs text-accent" aria-hidden>
            {glyph}
          </span>
        )}
        <div className="text-sm font-medium leading-snug">{d.title}</div>
      </div>
      {d.kind && d.kind !== "concept" && (
        <div className="mt-1 text-[10px] uppercase tracking-wide text-muted">{d.kind}</div>
      )}
      {d.flagged && <div className="mt-1 text-[10px] text-warn">low confidence</div>}
      <Handle type="source" position={Position.Bottom} className="!bg-border" />
    </div>
  );
}

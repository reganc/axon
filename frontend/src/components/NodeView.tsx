"use client";
import { useEffect, useState } from "react";
import { useGraphStore } from "@/store/graphStore";

/** Opens the selected node: the curiosity hook first, then (on reveal) the body,
 *  then a "pull this thread" affordance — or, for a question node, an "explore"
 *  affordance that asks the companion to build the answer-subgraph. */
export function NodeView({
  onPullThread,
  onExploreQuestion,
}: {
  onPullThread: (nodeId: string) => void;
  onExploreQuestion: (nodeId: string) => void;
}) {
  const selectedId = useGraphStore((s) => s.selectedId);
  const node = useGraphStore((s) => (s.selectedId ? s.nodes[s.selectedId] : null));
  const [revealed, setRevealed] = useState(false);

  // collapse the body again whenever a different node is opened
  useEffect(() => setRevealed(false), [selectedId]);

  if (!node) {
    return (
      <div className="p-4 text-sm text-muted">
        Select a node to read it — the hook first, then the explanation.
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto p-4">
      <div className="text-xs uppercase tracking-wide text-muted">
        {node.onSpine ? "spine" : "web"} · {node.origin ?? "?"}
        {typeof node.confidence === "number" ? ` · conf ${node.confidence.toFixed(2)}` : ""}
      </div>
      <h2 className="text-lg font-semibold text-fg">{node.title}</h2>

      {node.hook && <p className="text-fg">{node.hook}</p>}

      {node.kind === "question" ? (
        // a question has no answer body — opening it seeds generation
        <p className="text-sm italic text-muted">
          An open question. Explore it and the companion builds the concepts that answer it.
        </p>
      ) : !revealed ? (
        <button
          type="button"
          onClick={() => setRevealed(true)}
          className="self-start rounded-md border border-border bg-surface-2 px-3 py-1.5 text-sm text-fg hover:bg-surface"
        >
          Reveal explanation
        </button>
      ) : (
        <p className="whitespace-pre-wrap text-sm text-muted">{node.body ?? "—"}</p>
      )}

      {node.kind === "question" ? (
        <button
          type="button"
          onClick={() => onExploreQuestion(node.id)}
          disabled={node.optimistic}
          className="mt-auto rounded-md bg-accent px-3 py-2 text-sm font-medium text-accent-fg disabled:opacity-50"
        >
          Explore this question →
        </button>
      ) : (
        <button
          type="button"
          onClick={() => onPullThread(node.id)}
          disabled={node.optimistic}
          className="mt-auto rounded-md bg-accent px-3 py-2 text-sm font-medium text-accent-fg disabled:opacity-50"
        >
          Pull this thread →
        </button>
      )}
    </div>
  );
}

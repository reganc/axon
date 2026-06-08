"use client";
import { useEffect, useState } from "react";
import { kindGlyph } from "@/lib/kind";
import { ctaAria, ctaLabel } from "@/lib/prompts";
import { type GNode, useGraphStore } from "@/store/graphStore";

interface Props {
  nodeId: string;
  onClose: () => void;
  onExplore: (node: GNode) => void;
}

/** Focused reader for one card: the hook first, the explanation on reveal, then
 *  the same "go deeper" CTA. A lightbox over the deck — close on Esc/backdrop. */
export function CardDetail({ nodeId, onClose, onExplore }: Props) {
  const node = useGraphStore((s) => s.nodes[nodeId]);
  const [revealed, setRevealed] = useState(false);

  useEffect(() => setRevealed(false), [nodeId]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (!node) return null;
  const isQuestion = node.kind === "question";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-overlay p-4 backdrop-blur-sm"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="animate-pop-in flex max-h-[85vh] w-full max-w-xl flex-col overflow-y-auto rounded-2xl border border-border bg-surface p-6 shadow-md"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={node.title}
      >
        <div className="mb-3 flex items-start justify-between gap-3">
          <h2 className="text-xl font-semibold text-fg">
            <span className="mr-2 text-accent" aria-hidden="true">
              {kindGlyph(node.kind)}
            </span>
            {node.title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-md p-1 text-muted hover:bg-surface-2 hover:text-fg"
          >
            ✕
          </button>
        </div>

        {node.hook && <p className="text-fg">{node.hook}</p>}

        {isQuestion ? (
          <p className="mt-3 text-sm italic text-muted">
            An open question — go after it and the companion builds the ideas that answer it.
          </p>
        ) : !revealed ? (
          <button
            type="button"
            onClick={() => setRevealed(true)}
            className="mt-4 self-start rounded-md border border-border bg-surface-2 px-3 py-1.5 text-sm text-fg hover:bg-surface"
          >
            Reveal explanation
          </button>
        ) : (
          <p className="mt-3 whitespace-pre-wrap text-sm text-muted">{node.body ?? "—"}</p>
        )}

        <button
          type="button"
          onClick={() => onExplore(node)}
          disabled={node.optimistic}
          aria-label={ctaAria(node.kind)}
          className="mt-6 self-start rounded-full bg-accent px-5 py-2 text-sm font-medium text-accent-fg disabled:opacity-40"
        >
          {ctaLabel(node.kind, node.id)}
        </button>
      </div>
    </div>
  );
}

"use client";
import { useEffect, useRef, useState } from "react";
import { kindGlyph } from "@/lib/kind";
import { ctaAria, ctaLabel } from "@/lib/prompts";
import { type GNode, useGraphStore } from "@/store/graphStore";
import { useTranscriptStore } from "@/store/transcriptStore";

interface Props {
  nodeId: string;
  onClose: () => void;
  onExplore: (node: GNode) => void;
  /** Start a streamed, spoken deep-dive on this card. */
  onDeepDive: (nodeId: string) => void;
}

/** Focused reader for one card. Opening it asks the companion for a streamed,
 *  conversational deep-dive (typed out live, spoken if voice is on), and shows
 *  the canonical notes underneath. New study materials it generates appear as
 *  cards in the deck. A lightbox over the deck — close on Esc/backdrop. */
export function CardDetail({ nodeId, onClose, onExplore, onDeepDive }: Props) {
  const node = useGraphStore((s) => s.nodes[nodeId]);
  const deepDive = useTranscriptStore((s) => s.deepDives[nodeId]);
  const busy = useTranscriptStore((s) => s.busy);
  const [revealed, setRevealed] = useState(false);
  const requested = useRef<Set<string>>(new Set());

  useEffect(() => setRevealed(false), [nodeId]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // On open, kick off the deep-dive once per card (unless we already have it, or
  // the card is still building / is a question seed).
  const isQuestion = node?.kind === "question";
  useEffect(() => {
    if (!node || isQuestion || node.optimistic) return;
    if (deepDive || requested.current.has(nodeId)) return;
    requested.current.add(nodeId);
    onDeepDive(nodeId);
  }, [nodeId, node, isQuestion, deepDive, onDeepDive]);

  if (!node) return null;
  const diving = busy && !deepDive;

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
        ) : (
          <section className="mt-4" aria-label="Companion explanation">
            {diving && (
              <p className="animate-pulse text-sm italic text-muted">Jarvis is thinking…</p>
            )}
            {deepDive && (
              <p className="whitespace-pre-wrap leading-relaxed text-fg">{deepDive}</p>
            )}
            {node.body &&
              (revealed ? (
                <p className="mt-4 whitespace-pre-wrap border-t border-border pt-3 text-sm text-muted">
                  {node.body}
                </p>
              ) : (
                <button
                  type="button"
                  onClick={() => setRevealed(true)}
                  className="mt-4 self-start rounded-md border border-border bg-surface-2 px-3 py-1.5 text-sm text-fg hover:bg-surface"
                >
                  Show the notes
                </button>
              ))}
          </section>
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

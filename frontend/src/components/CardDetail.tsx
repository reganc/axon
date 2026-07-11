"use client";
import { useEffect, useRef, useState } from "react";
import { kindGlyph } from "@/lib/kind";
import { ctaAria, ctaLabel } from "@/lib/prompts";
import { type GNode, useGraphStore } from "@/store/graphStore";
import { useTranscriptStore } from "@/store/transcriptStore";
import { MediaPanel } from "./MediaPanel";

// Mirrors the backend clamp (AXON_COMPANION_MAX_DIVE_DEPTH); the button hides
// once the ladder tops out.
const MAX_DIVE_DEPTH = 3;

interface Props {
  nodeId: string;
  onClose: () => void;
  onExplore: (node: GNode) => void;
  /** Start a streamed, spoken deep-dive on this card. depth>0 asks for a
   *  genuinely deeper pass (the go-deeper ladder). */
  onDeepDive: (nodeId: string, depth?: number) => void;
  /** Ask a node-scoped follow-up — keeps the conversation on this card. */
  onDiscuss: (nodeId: string, text: string) => void;
  /** Pull up visual aids (video, diagram, links, mini-graph) for this card. */
  onRequestMedia: (nodeId: string) => void;
}

/** Focused reader for one card. Opening it asks the companion for a streamed,
 *  conversational deep-dive (typed out live, spoken if voice is on), and shows
 *  the canonical notes underneath. Below that, a discussion thread: ask a
 *  follow-up about *this* card and the companion answers in place — and when an
 *  answer surfaces a genuinely new concept it lands as a fresh card in the deck.
 *  A lightbox over the deck — close on Esc/backdrop. */
export function CardDetail({
  nodeId,
  onClose,
  onExplore,
  onDeepDive,
  onDiscuss,
  onRequestMedia,
}: Props) {
  const node = useGraphStore((s) => s.nodes[nodeId]);
  const deepDive = useTranscriptStore((s) => s.deepDives[nodeId]);
  const thread = useTranscriptStore((s) => s.discussions[nodeId]);
  const media = useTranscriptStore((s) => s.media[nodeId]);
  const busy = useTranscriptStore((s) => s.busy);
  const [revealed, setRevealed] = useState(false);
  const [followUp, setFollowUp] = useState("");
  const requested = useRef<Set<string>>(new Set());
  const mediaRequested = useRef<Set<string>>(new Set());
  const threadEndRef = useRef<HTMLDivElement>(null);
  // Go-deeper ladder: how many deeper passes this card has been asked for
  // (per node, survives switching cards within the open reader).
  const depths = useRef<Record<string, number>>({});
  const [deepening, setDeepening] = useState(false);

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

  // On open, pull up visual aids once per card (unless we already have them, or
  // the card is still building / is a question seed).
  useEffect(() => {
    if (!node || isQuestion || node.optimistic) return;
    if ((media && media.length > 0) || mediaRequested.current.has(nodeId)) return;
    mediaRequested.current.add(nodeId);
    onRequestMedia(nodeId);
  }, [nodeId, node, isQuestion, media, onRequestMedia]);

  // Keep the newest turn in view as the answer streams in.
  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ block: "nearest" });
  }, [thread]);

  // The deeper pass has landed once the turn finishes.
  useEffect(() => {
    if (!busy) setDeepening(false);
  }, [busy]);

  if (!node) return null;
  const diving = busy && !deepDive;
  const depth = depths.current[nodeId] ?? 0;
  const goDeeper = () => {
    const next = Math.min(depth + 1, MAX_DIVE_DEPTH);
    depths.current[nodeId] = next;
    setDeepening(true);
    onDeepDive(nodeId, next);
  };
  const awaitingReply =
    busy && thread !== undefined && thread.length > 0 && thread[thread.length - 1].role === "learner";

  const submitFollowUp = () => {
    const v = followUp.trim();
    if (!v) return;
    onDiscuss(nodeId, v);
    setFollowUp("");
  };

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
            {deepening && (
              <p className="mt-2 animate-pulse text-sm italic text-muted">
                Jarvis is digging deeper…
              </p>
            )}
            {deepDive && !busy && depth < MAX_DIVE_DEPTH && (
              <button
                type="button"
                onClick={goDeeper}
                disabled={node.optimistic}
                className="mt-3 self-start rounded-full border border-accent px-4 py-1.5 text-sm font-medium text-accent hover:bg-accent hover:text-accent-fg disabled:opacity-40"
              >
                Go deeper
              </button>
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

        {!isQuestion && <MediaPanel items={media} />}

        {!isQuestion && (
          <section className="mt-5 border-t border-border pt-4" aria-label="Discussion">
            {thread && thread.length > 0 && (
              <ul className="mb-3 flex flex-col gap-2">
                {thread.map((turn, i) => (
                  <li
                    key={`${turn.role}-${i}`}
                    className={
                      turn.role === "learner"
                        ? "self-end rounded-2xl rounded-br-sm bg-accent px-3 py-2 text-sm text-accent-fg"
                        : "self-start rounded-2xl rounded-bl-sm bg-surface-2 px-3 py-2 text-sm text-fg"
                    }
                  >
                    {turn.text}
                  </li>
                ))}
              </ul>
            )}
            {awaitingReply && (
              <p className="mb-2 animate-pulse text-sm italic text-muted">Jarvis is thinking…</p>
            )}
            <div className="flex items-center gap-2">
              <input
                value={followUp}
                onChange={(e) => setFollowUp(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && submitFollowUp()}
                disabled={node.optimistic}
                placeholder="Ask a follow-up about this…"
                aria-label="Ask a follow-up about this card"
                className="flex-1 rounded-full border border-border bg-bg px-4 py-2 text-sm text-fg outline-none focus:border-accent disabled:opacity-40"
              />
              <button
                type="button"
                onClick={submitFollowUp}
                disabled={node.optimistic || !followUp.trim()}
                className="rounded-full bg-accent px-4 py-2 text-sm font-medium text-accent-fg disabled:opacity-40"
              >
                Ask
              </button>
            </div>
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

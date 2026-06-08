"use client";
import { kindGlyph } from "@/lib/kind";
import { ctaAria, ctaLabel } from "@/lib/prompts";
import type { GNode } from "@/store/graphStore";

interface Props {
  node: GNode;
  onOpen: (id: string) => void;
  onExplore: (node: GNode) => void;
}

/** One concept as an inviting card: title, hook, and a playful "go deeper" CTA.
 *  The card body opens the reader; the CTA pulls the thread to grow the deck.
 *  Structure (spine/web, how it was generated) is intentionally not shown. */
export function ConceptCard({ node, onOpen, onExplore }: Props) {
  const pending = node.optimistic;

  return (
    <div
      data-testid="concept-card"
      className={`group relative flex min-h-[10rem] flex-col rounded-2xl border border-border bg-surface p-5 shadow-sm transition-[transform,border-color,box-shadow] hover:-translate-y-1 hover:border-accent hover:shadow-md ${
        pending ? "animate-pulse" : "animate-pop-in"
      }`}
    >
      <button
        type="button"
        onClick={() => onOpen(node.id)}
        className="flex flex-1 flex-col items-start text-left"
        aria-label={`Open ${node.title}`}
      >
        <span className="mb-2 text-lg text-accent" aria-hidden="true">
          {kindGlyph(node.kind)}
        </span>
        <h3 className="text-base font-semibold leading-snug text-fg">{node.title}</h3>
        {node.hook && (
          <p className="mt-2 line-clamp-3 text-sm text-muted">{node.hook}</p>
        )}
        {node.flagged && (
          <span className="mt-2 text-xs text-warn">worth a second look</span>
        )}
      </button>

      <button
        type="button"
        onClick={() => onExplore(node)}
        disabled={pending}
        aria-label={ctaAria(node.kind)}
        className="mt-4 self-start rounded-full bg-accent px-4 py-1.5 text-sm font-medium text-accent-fg transition disabled:opacity-40 group-hover:px-5"
      >
        {pending ? "building…" : ctaLabel(node.kind, node.id)}
      </button>
    </div>
  );
}

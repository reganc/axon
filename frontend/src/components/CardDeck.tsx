"use client";
import { useMemo } from "react";
import { idleNudge } from "@/lib/prompts";
import { type GNode, useGraphStore } from "@/store/graphStore";
import { useTranscriptStore } from "@/store/transcriptStore";
import { ConceptCard } from "./ConceptCard";

interface Props {
  onOpen: (id: string) => void;
  onExplore: (node: GNode) => void;
  subjectHint: string;
}

/** The learning surface: a deck of concept cards filling the view, newest first,
 *  with a soft "thinking" tile while the companion works. No spine, no status,
 *  no chat log — just options to pull from. */
export function CardDeck({ onOpen, onExplore, subjectHint }: Props) {
  const nodes = useGraphStore((s) => s.nodes);
  const order = useGraphStore((s) => s.order);
  const busy = useTranscriptStore((s) => s.busy);

  const cards = useMemo(
    () => order.filter((id) => nodes[id]).reverse(),
    [order, nodes],
  );

  if (cards.length === 0 && !busy) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-center">
        <p className="max-w-md text-xl font-medium text-muted">
          {idleNudge(subjectHint || "start")}
        </p>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto p-5 sm:p-8">
      <div className="mx-auto grid max-w-6xl grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {busy && (
          <div className="flex min-h-[10rem] animate-pulse flex-col justify-center rounded-2xl border border-border bg-surface-2 p-5">
            <span className="text-sm italic text-muted">Jarvis is thinking…</span>
          </div>
        )}
        {cards.map((id) => (
          <ConceptCard key={id} node={nodes[id]} onOpen={onOpen} onExplore={onExplore} />
        ))}
      </div>
    </div>
  );
}

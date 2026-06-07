"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { AuthGuard } from "@/components/AuthGuard";
import { CompanionPanel } from "@/components/CompanionPanel";
import { GraphCanvas } from "@/components/GraphCanvas";
import { NodeView } from "@/components/NodeView";
import { ThemeToggle } from "@/components/ThemeToggle";
import { getSpine } from "@/lib/api";
import { useCompanionStream } from "@/lib/useCompanionStream";
import { useGraphStore } from "@/store/graphStore";
import { useTranscriptStore } from "@/store/transcriptStore";

function LearnInner({ checkoutId }: { checkoutId: string }) {
  const initGraph = useGraphStore((s) => s.init);
  const initTranscript = useTranscriptStore((s) => s.init);
  const [title, setTitle] = useState<string | null>(null);
  const { connected, sendSubject, answer, interrupt, pullThread, exploreQuestion } =
    useCompanionStream(checkoutId);

  useEffect(() => {
    if (typeof window !== "undefined") {
      setTitle(sessionStorage.getItem(`axon.spine.title.${checkoutId}`));
    }
    initGraph(checkoutId);
    initTranscript(checkoutId);
    // Seed the canvas with the checked-out spine (highlighted path) unless we
    // already restored a persisted graph for this checkout.
    const spineId =
      typeof window !== "undefined" ? sessionStorage.getItem(`axon.spine.${checkoutId}`) : null;
    if (spineId && Object.keys(useGraphStore.getState().nodes).length === 0) {
      getSpine(spineId)
        .then((s) => useGraphStore.getState().seedSpine(s.nodes))
        .catch(() => {
          /* spine may have been removed; the canvas just starts empty */
        });
    }
  }, [checkoutId, initGraph, initTranscript]);

  return (
    <div className="flex h-screen flex-col">
      <header className="flex items-center justify-between border-b border-border bg-surface px-4 py-2">
        <div className="flex items-center gap-2 text-sm">
          <Link href="/library" className="text-muted hover:text-fg">
            Library
          </Link>
          <span className="text-muted">/</span>
          <span className="font-medium text-fg">{title ?? "Learning canvas"}</span>
        </div>
        <ThemeToggle />
      </header>

      <div className="flex min-h-0 flex-1">
        <div className="min-w-0 flex-1">
          <GraphCanvas />
        </div>
        <aside className="flex w-[380px] flex-col border-l border-border">
          <div className="h-1/2 min-h-0 overflow-hidden border-b border-border bg-surface">
            <NodeView onPullThread={pullThread} onExploreQuestion={exploreQuestion} />
          </div>
          <div className="h-1/2 min-h-0">
            <CompanionPanel
              connected={connected}
              onSubject={sendSubject}
              onAnswer={answer}
              onInterrupt={interrupt}
            />
          </div>
        </aside>
      </div>
    </div>
  );
}

export default function LearnPage() {
  const params = useParams<{ checkoutId: string }>();
  return (
    <AuthGuard>
      <LearnInner checkoutId={params.checkoutId} />
    </AuthGuard>
  );
}

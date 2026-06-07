"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { AuthGuard } from "@/components/AuthGuard";
import { CompanionPanel } from "@/components/CompanionPanel";
import { GraphCanvas } from "@/components/GraphCanvas";
import { NodeView } from "@/components/NodeView";
import { ThemeToggle } from "@/components/ThemeToggle";
import { getConversation, getSpine } from "@/lib/api";
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

    const seedSpine = () => {
      const spineId =
        typeof window !== "undefined" ? sessionStorage.getItem(`axon.spine.${checkoutId}`) : null;
      if (spineId) {
        getSpine(spineId)
          .then((s) => useGraphStore.getState().seedSpine(s.nodes))
          .catch(() => {});
      }
    };

    // If nothing was restored from this tab's sessionStorage (fresh tab, a resumed
    // session, or another device), rebuild from the durable server-side log so the
    // conversation + canvas come back — then layer the spine path on top.
    if (Object.keys(useGraphStore.getState().nodes).length === 0) {
      getConversation(checkoutId)
        .then((events) => {
          const g = useGraphStore.getState();
          const t = useTranscriptStore.getState();
          for (const ev of events) {
            if (ev.type === "node.create" || ev.type === "node.update" || ev.type === "edge.create") {
              g.apply(ev);
            } else {
              t.apply(ev);
            }
          }
        })
        .catch(() => {})
        .finally(seedSpine);
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

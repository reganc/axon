"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { AuthGuard } from "@/components/AuthGuard";
import { CardDeck } from "@/components/CardDeck";
import { CardDetail } from "@/components/CardDetail";
import { CompanionBar } from "@/components/CompanionBar";
import { GraphCanvas } from "@/components/GraphCanvas";
import { ThemeToggle } from "@/components/ThemeToggle";
import { getConversation, getSpine } from "@/lib/api";
import { useCompanionStream } from "@/lib/useCompanionStream";
import { speak, stopSpeaking } from "@/lib/voice";
import { type GNode, useGraphStore } from "@/store/graphStore";
import { useTranscriptStore } from "@/store/transcriptStore";

const VOICE_PREF_KEY = "axon.voice.speak";
type View = "cards" | "map";

function LearnInner({ checkoutId }: { checkoutId: string }) {
  const initGraph = useGraphStore((s) => s.init);
  const initTranscript = useTranscriptStore((s) => s.init);
  const select = useGraphStore((s) => s.select);
  const selectedId = useGraphStore((s) => s.selectedId);
  const [title, setTitle] = useState<string | null>(null);
  const [speakEnabled, setSpeakEnabled] = useState(false);
  const [view, setView] = useState<View>("cards");
  const [openId, setOpenId] = useState<string | null>(null);

  useEffect(() => {
    if (typeof window !== "undefined") {
      setSpeakEnabled(localStorage.getItem(VOICE_PREF_KEY) === "on");
    }
  }, []);

  // In map view, clicking a graph node opens the same reader as a card.
  useEffect(() => {
    if (view === "map" && selectedId) setOpenId(selectedId);
  }, [view, selectedId]);

  const closeDetail = () => {
    setOpenId(null);
    select(null);
  };

  const toggleSpeak = () => {
    setSpeakEnabled((prev) => {
      const next = !prev;
      if (typeof window !== "undefined") {
        localStorage.setItem(VOICE_PREF_KEY, next ? "on" : "off");
      }
      if (!next) stopSpeaking();
      return next;
    });
  };

  const {
    connected,
    sendSubject,
    answer,
    interrupt,
    pullThread,
    exploreQuestion,
    explain,
  } = useCompanionStream(checkoutId, speakEnabled ? speak : undefined);

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

  const onExplore = (node: GNode) => {
    if (node.kind === "question") exploreQuestion(node.id);
    else pullThread(node.id);
    closeDetail();
  };

  return (
    <div className="flex h-screen flex-col">
      <header className="flex items-center justify-between border-b border-border bg-surface px-4 py-2">
        <div className="flex items-center gap-2 text-sm">
          <Link href="/library" className="text-muted hover:text-fg">
            Library
          </Link>
          <span className="text-muted">/</span>
          <span className="font-medium text-fg">{title ?? "Learning"}</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex rounded-full border border-border bg-surface p-0.5 text-xs">
            {(["cards", "map"] as const).map((v) => (
              <button
                key={v}
                type="button"
                onClick={() => setView(v)}
                aria-pressed={view === v}
                className={`rounded-full px-3 py-1 capitalize transition ${
                  view === v ? "bg-accent text-accent-fg" : "text-muted hover:text-fg"
                }`}
              >
                {v}
              </button>
            ))}
          </div>
          <ThemeToggle />
        </div>
      </header>

      <main className="min-h-0 flex-1">
        {view === "cards" ? (
          <CardDeck onOpen={setOpenId} onExplore={onExplore} subjectHint={title ?? ""} />
        ) : (
          <GraphCanvas />
        )}
      </main>

      <CompanionBar
        connected={connected}
        onSubject={sendSubject}
        onAnswer={answer}
        onInterrupt={interrupt}
        speakEnabled={speakEnabled}
        onToggleSpeak={toggleSpeak}
      />

      {openId && (
        <CardDetail
          nodeId={openId}
          onClose={closeDetail}
          onExplore={onExplore}
          onDeepDive={explain}
        />
      )}
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

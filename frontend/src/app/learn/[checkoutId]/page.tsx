"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { AuthGuard } from "@/components/AuthGuard";
import { CardDeck } from "@/components/CardDeck";
import { CardDetail } from "@/components/CardDetail";
import { CompanionBar } from "@/components/CompanionBar";
import { GraphCanvas } from "@/components/GraphCanvas";
import { LevelSelector } from "@/components/LevelSelector";
import { ThemeToggle } from "@/components/ThemeToggle";
import { getConversation, getSpine } from "@/lib/api";
import type { DeliveryLevel } from "@/lib/types";
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
  const [level, setLevelState] = useState<DeliveryLevel | null>(null);
  // Mirror openId into a ref so the stable onSay callback always sees the
  // current card without re-subscribing the socket.
  const openIdRef = useRef<string | null>(null);
  openIdRef.current = openId;

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
    // Closing the card cuts the narration immediately — the deep-dive text
    // still completes silently in the store, but the voice stops with the card.
    stopSpeaking();
    setOpenId(null);
    select(null);
  };

  // Speak live narration, but mute lines pinned to a card that isn't open
  // (e.g. a deep-dive still streaming after the learner closed the card).
  // General narration (no nodeId) always speaks.
  const onSay = useCallback((text: string, nodeId?: string) => {
    if (nodeId && nodeId !== openIdRef.current) return;
    speak(text);
  }, []);

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
    fatal,
    sendSubject,
    answer,
    interrupt,
    pullThread,
    exploreQuestion,
    explain,
    discuss,
    setLevel,
    requestMedia,
  } = useCompanionStream(checkoutId, speakEnabled ? onSay : undefined);

  // Apply the chosen level to the live session (and re-apply on change). The hook
  // also re-sends it on every reconnect, so the choice survives blips.
  useEffect(() => {
    setLevel(level);
  }, [level, setLevel]);

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

  // Asking a follow-up on a card is a barge-in too: the deep-dive narration
  // stops so the answer doesn't queue behind it (the backend already cancels
  // the superseded stream; this drops the clips that were already in flight).
  const onDiscuss = useCallback(
    (nodeId: string, text: string) => {
      stopSpeaking();
      discuss(nodeId, text);
    },
    [discuss],
  );

  const onExplore = (node: GNode) => {
    if (node.kind === "question") exploreQuestion(node.id);
    else pullThread(node.id);
    closeDetail();
  };

  if (fatal) {
    return (
      <div className="flex h-screen flex-col items-center justify-center gap-4 bg-bg px-6 text-center">
        <p className="text-lg font-medium text-fg">{fatal}</p>
        <p className="max-w-md text-sm text-muted">
          This learning session can&apos;t be reopened. Start a new one from the
          library.
        </p>
        <Link
          href="/library"
          className="rounded-full bg-accent px-4 py-2 text-sm text-accent-fg"
        >
          Back to Library
        </Link>
      </div>
    );
  }

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
          <LevelSelector value={level} onChange={setLevelState} />
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
          onDiscuss={onDiscuss}
          onRequestMedia={requestMedia}
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

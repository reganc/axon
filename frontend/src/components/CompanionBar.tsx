"use client";
import { useMemo, useState } from "react";
import { VoiceControls } from "@/components/VoiceControls";
import { stopSpeaking } from "@/lib/voice";
import { useTranscriptStore } from "@/store/transcriptStore";

interface Props {
  connected: boolean;
  onSubject: (text: string) => void;
  onAnswer: (text: string) => void;
  onInterrupt: (text: string) => void;
  speakEnabled: boolean;
  onToggleSpeak: () => void;
}

/** A slim companion bar pinned under the deck. It exposes only what the learner
 *  needs — voice, an input, quick replies, and the companion's current line —
 *  and deliberately hides the processing log (status events) and structure. */
export function CompanionBar({
  connected,
  onSubject,
  onAnswer,
  onInterrupt,
  speakEnabled,
  onToggleSpeak,
}: Props) {
  const messages = useTranscriptStore((s) => s.messages);
  const ask = useTranscriptStore((s) => s.ask);
  const busy = useTranscriptStore((s) => s.busy);
  const [text, setText] = useState("");

  // The companion's latest spoken line — shown as a subtle subtitle, not a log.
  const lastSay = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].kind === "say") return messages[i].text;
    }
    return null;
  }, [messages]);

  const route = (value: string) => {
    const v = value.trim();
    if (!v) return;
    if (ask) onAnswer(v);
    else if (busy) onInterrupt(v);
    else onSubject(v);
  };

  const submit = () => {
    route(text);
    setText("");
  };

  return (
    <div className="border-t border-border bg-surface px-4 py-3">
      {ask?.options && ask.options.length > 0 && (
        <div className="mx-auto mb-2 flex max-w-3xl flex-wrap gap-2">
          {ask.options.map((opt) => (
            <button
              key={opt}
              type="button"
              onClick={() => onAnswer(opt)}
              className="rounded-full border border-accent bg-surface px-3 py-1 text-xs text-fg hover:bg-surface-2"
            >
              {opt}
            </button>
          ))}
        </div>
      )}

      {(lastSay || busy) && (
        <p className="mx-auto mb-2 max-w-3xl truncate text-center text-sm italic text-muted">
          {/* Stream the narration live; only fall back to a thinking cue before
              the first line of a turn arrives. */}
          {lastSay ?? "Jarvis is thinking…"}
        </p>
      )}

      <div className="mx-auto flex max-w-3xl items-center gap-2">
        <VoiceControls
          speakEnabled={speakEnabled}
          onToggleSpeak={onToggleSpeak}
          onText={route}
          onListenStart={stopSpeaking}
        />
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          placeholder={ask ? "Answer…" : busy ? "Interrupt…" : "Teach me about…"}
          className="flex-1 rounded-full border border-border bg-bg px-4 py-2 text-sm text-fg outline-none focus:border-accent"
        />
        <button
          type="button"
          onClick={submit}
          className="rounded-full bg-accent px-5 py-2 text-sm font-medium text-accent-fg"
        >
          {ask ? "Answer" : busy ? "Interrupt" : "Send"}
        </button>
        <span
          className={`hidden text-xs sm:inline ${connected ? "text-accent" : "text-muted"}`}
          title={connected ? "connected" : "offline"}
        >
          {connected ? "● live" : "○ offline"}
        </span>
      </div>
    </div>
  );
}

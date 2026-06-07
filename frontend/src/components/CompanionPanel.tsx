"use client";
import { useEffect, useRef, useState } from "react";
import { useTranscriptStore } from "@/store/transcriptStore";

interface Props {
  connected: boolean;
  onSubject: (text: string) => void;
  onAnswer: (text: string) => void;
  onInterrupt: (text: string) => void;
}

/** Chat-style companion: `say`/`status` render as bubbles, an `ask` pauses the
 *  flow and shows quick-reply chips; the input sends answer / interrupt / subject
 *  depending on state. (Voice tier 1 = streamed text; TTS is a later tier.) */
export function CompanionPanel({ connected, onSubject, onAnswer, onInterrupt }: Props) {
  const messages = useTranscriptStore((s) => s.messages);
  const ask = useTranscriptStore((s) => s.ask);
  const busy = useTranscriptStore((s) => s.busy);
  const [text, setText] = useState("");
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, ask]);

  const submit = () => {
    const value = text.trim();
    if (!value) return;
    if (ask) onAnswer(value);
    else if (busy) onInterrupt(value);
    else onSubject(value);
    setText("");
  };

  return (
    <div className="flex h-full flex-col border-l border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-4 py-2 text-sm">
        <span className="font-medium text-fg">Companion</span>
        <span className={connected ? "text-accent" : "text-muted"}>
          {connected ? "● live" : "○ offline"}
        </span>
      </div>

      <div className="flex-1 space-y-2 overflow-y-auto p-3">
        {messages.length === 0 && (
          <p className="text-sm text-muted">
            Name a subject and the companion will build the graph live.
          </p>
        )}
        {messages.map((m) =>
          m.kind === "status" ? (
            <div key={m.id} className="text-center text-xs italic text-muted">
              {m.text}
            </div>
          ) : (
            <div
              key={m.id}
              className="max-w-[90%] rounded-lg bg-surface-2 px-3 py-2 text-sm text-fg"
            >
              {m.text}
            </div>
          ),
        )}
        {busy && !ask && <div className="text-xs italic text-muted">…thinking</div>}
        <div ref={endRef} />
      </div>

      {ask?.options && ask.options.length > 0 && (
        <div className="flex flex-wrap gap-2 border-t border-border px-3 py-2">
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

      <div className="flex gap-2 border-t border-border p-3">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          placeholder={ask ? "Answer…" : busy ? "Interrupt…" : "Teach me about…"}
          className="flex-1 rounded-md border border-border bg-bg px-3 py-2 text-sm text-fg outline-none focus:border-accent"
        />
        <button
          type="button"
          onClick={submit}
          className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-fg"
        >
          {ask ? "Answer" : busy ? "Interrupt" : "Send"}
        </button>
      </div>
    </div>
  );
}

"use client";
import { useMic } from "@/lib/useMic";
import { transcribe } from "@/lib/voice";

interface Props {
  /** Whether Jarvis speaks `say` events aloud (TTS output). */
  speakEnabled: boolean;
  onToggleSpeak: () => void;
  /** Receives the transcript of a recorded mic clip. */
  onText: (text: string) => void;
  /** Called when the mic opens, so TTS can be cut off (barge-in). */
  onListenStart?: () => void;
}

/** Speaker toggle (TTS on/off) + push-to-talk mic (STT). Colors are tokens. */
export function VoiceControls({ speakEnabled, onToggleSpeak, onText, onListenStart }: Props) {
  const { recording, error, toggle } = useMic(async (blob) => {
    try {
      const text = await transcribe(blob);
      if (text) onText(text);
    } catch {
      /* swallow — STT is best-effort */
    }
  });

  const onMic = () => {
    if (!recording) onListenStart?.();
    toggle();
  };

  return (
    <div className="flex items-center gap-1">
      <button
        type="button"
        onClick={onToggleSpeak}
        aria-pressed={speakEnabled}
        title={speakEnabled ? "Jarvis voice: on" : "Jarvis voice: off"}
        className={`rounded-md p-1.5 hover:bg-surface-2 ${
          speakEnabled ? "text-accent" : "text-muted"
        }`}
      >
        <SpeakerIcon muted={!speakEnabled} />
      </button>
      <button
        type="button"
        onClick={onMic}
        aria-pressed={recording}
        title={error ?? (recording ? "Listening — click to stop" : "Hold a thought — click to talk")}
        className={`rounded-md p-1.5 ${
          recording
            ? "animate-pulse bg-accent text-accent-fg"
            : error
              ? "text-warn"
              : "text-muted hover:bg-surface-2"
        }`}
      >
        <MicIcon />
      </button>
    </div>
  );
}

function MicIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="9" y="2" width="6" height="12" rx="3" />
      <path d="M5 10a7 7 0 0 0 14 0" />
      <line x1="12" y1="17" x2="12" y2="22" />
    </svg>
  );
}

function SpeakerIcon({ muted }: { muted: boolean }) {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M11 5 6 9H3v6h3l5 4V5z" />
      {muted ? (
        <line x1="22" y1="9" x2="16" y2="15" />
      ) : (
        <path d="M15.5 8.5a5 5 0 0 1 0 7" />
      )}
    </svg>
  );
}

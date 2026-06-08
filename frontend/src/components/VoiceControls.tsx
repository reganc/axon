"use client";
import { useCallback, useEffect, useState } from "react";
import { voiceConfig } from "@/lib/config";
import { useMic } from "@/lib/useMic";
import { useWakeWord } from "@/lib/useWakeWord";
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

const WAKE_PREF_KEY = "axon.voice.wake";
// Hands-free capture thresholds come from config (NEXT_PUBLIC_AXON_VAD_*).
const CAPTURE_OPTS = voiceConfig.vad;

/** Speaker toggle (TTS), "Hey Jarvis" wake toggle, and a push-to-talk mic. The
 *  wake word arms the same mic capture hands-free. Colors are design tokens. */
export function VoiceControls({ speakEnabled, onToggleSpeak, onText, onListenStart }: Props) {
  const [wakeOn, setWakeOn] = useState(false);
  const [transcribing, setTranscribing] = useState(false);

  useEffect(() => {
    if (typeof window !== "undefined") {
      setWakeOn(localStorage.getItem(WAKE_PREF_KEY) === "on");
    }
  }, []);

  const handleClip = useCallback(
    async (blob: Blob) => {
      setTranscribing(true);
      try {
        const text = await transcribe(blob);
        if (text) onText(text);
      } catch {
        /* swallow — STT is best-effort */
      } finally {
        setTranscribing(false);
      }
    },
    [onText],
  );

  const mic = useMic(handleClip, CAPTURE_OPTS);
  const busyMic = mic.recording || transcribing;

  // Wake fires -> cut off Jarvis and arm the mic (auto-stops on silence).
  const onWake = useCallback(() => {
    onListenStart?.();
    void mic.start();
  }, [mic, onListenStart]);

  // Suppress wake detection while we're capturing/transcribing (one mic at a time).
  const wake = useWakeWord(wakeOn && !busyMic, onWake);

  const toggleWake = () => {
    setWakeOn((prev) => {
      const next = !prev;
      if (typeof window !== "undefined") {
        localStorage.setItem(WAKE_PREF_KEY, next ? "on" : "off");
      }
      return next;
    });
  };

  const onMic = () => {
    if (mic.recording) {
      mic.stop();
      return;
    }
    onListenStart?.();
    void mic.start();
  };

  const wakeListening = wakeOn && wake.active && !busyMic;

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

      {wake.supported && (
        <button
          type="button"
          onClick={toggleWake}
          aria-pressed={wakeOn}
          title={
            wakeOn
              ? 'Wake word on — say "Jarvis" to talk'
              : 'Wake word off — enable "Hey Jarvis"'
          }
          className={`rounded-md p-1.5 hover:bg-surface-2 ${
            wakeListening ? "animate-pulse text-accent" : wakeOn ? "text-accent" : "text-muted"
          }`}
        >
          <WakeIcon />
        </button>
      )}

      <button
        type="button"
        onClick={onMic}
        aria-pressed={mic.recording}
        title={
          mic.error ??
          (mic.recording
            ? "Listening — click to stop"
            : transcribing
              ? "Transcribing…"
              : "Click to talk")
        }
        className={`rounded-md p-1.5 ${
          mic.recording
            ? "animate-pulse bg-accent text-accent-fg"
            : mic.error
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
      {muted ? <line x1="22" y1="9" x2="16" y2="15" /> : <path d="M15.5 8.5a5 5 0 0 1 0 7" />}
    </svg>
  );
}

function WakeIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="2.5" />
      <path d="M6.3 6.3a8 8 0 0 0 0 11.4M17.7 6.3a8 8 0 0 1 0 11.4" />
    </svg>
  );
}

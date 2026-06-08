"use client";
import { useEffect, useRef, useState } from "react";

// Minimal typing for the Web Speech API (not in the default DOM lib, and only
// shipped by Chromium browsers behind the webkit prefix). We use it purely as an
// always-on keyword spotter — the actual command is captured + transcribed by
// the self-hosted Whisper backend, not here.
interface SpeechResultAlternative {
  transcript: string;
}
interface SpeechRecognitionEventLike {
  resultIndex: number;
  results: ArrayLike<ArrayLike<SpeechResultAlternative>>;
}
interface SpeechRecognitionLike {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onresult: ((ev: SpeechRecognitionEventLike) => void) | null;
  onend: (() => void) | null;
  onerror: ((ev: { error: string }) => void) | null;
}
type SpeechRecognitionCtor = new () => SpeechRecognitionLike;
interface SpeechWindow {
  SpeechRecognition?: SpeechRecognitionCtor;
  webkitSpeechRecognition?: SpeechRecognitionCtor;
}

function getCtor(): SpeechRecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as SpeechWindow;
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

// "jarvis" plus the mishears the recognizer most often returns for it.
const WAKE = /\b(jarvis|jervis|jarvus|jarviss|service)\b/;
const COOLDOWN_MS = 2500;

/**
 * Listen continuously for the wake word while `enabled`. On a match, fire
 * `onWake` once (debounced by a cooldown). Auto-restarts the recognizer when the
 * browser ends a session, and tears down cleanly when disabled/unmounted.
 * Returns `supported` so the UI can hide the control where the API is absent.
 */
export function useWakeWord(enabled: boolean, onWake: () => void) {
  const [supported] = useState(() => getCtor() !== null);
  const [active, setActive] = useState(false);
  const recRef = useRef<SpeechRecognitionLike | null>(null);
  const enabledRef = useRef(enabled);
  const onWakeRef = useRef(onWake);
  const cooldownRef = useRef(false);
  onWakeRef.current = onWake;

  useEffect(() => {
    enabledRef.current = enabled;
    if (!supported) return;

    const start = () => {
      if (recRef.current) return;
      const Ctor = getCtor();
      if (!Ctor) return;
      const rec = new Ctor();
      rec.continuous = true;
      rec.interimResults = true;
      rec.lang = "en-US";
      rec.onresult = (ev) => {
        if (cooldownRef.current) return;
        for (let i = ev.resultIndex; i < ev.results.length; i++) {
          const alt = ev.results[i][0];
          if (alt && WAKE.test(alt.transcript.toLowerCase())) {
            cooldownRef.current = true;
            setTimeout(() => {
              cooldownRef.current = false;
            }, COOLDOWN_MS);
            onWakeRef.current();
            break;
          }
        }
      };
      rec.onerror = (e) => {
        if (e.error === "not-allowed" || e.error === "service-not-allowed") {
          enabledRef.current = false; // permission denied: don't thrash on restart
        }
      };
      rec.onend = () => {
        recRef.current = null;
        setActive(false);
        if (enabledRef.current) setTimeout(start, 300); // sessions end on their own
      };
      try {
        rec.start();
        recRef.current = rec;
        setActive(true);
      } catch {
        /* already started */
      }
    };

    const stop = () => {
      const rec = recRef.current;
      recRef.current = null;
      setActive(false);
      if (rec) {
        rec.onend = null; // suppress auto-restart
        try {
          rec.abort();
        } catch {
          /* nothing to abort */
        }
      }
    };

    if (enabled) start();
    else stop();
    return stop;
  }, [enabled, supported]);

  return { supported, active };
}

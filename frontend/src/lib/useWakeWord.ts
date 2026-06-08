"use client";
import { useEffect, useRef, useState } from "react";
import { DEFAULT_VOICE_CONFIG, type VoiceConfig } from "./config";

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

function wakeRegex(phrase: string): RegExp {
  // Accepted phrases (default: "jarvis" + common recognizer mishears),
  // word-boundary matched. Phrase comes from backend config.
  return new RegExp(`\\b(${phrase})\\b`);
}

/**
 * Listen continuously for the wake word while `enabled`. On a match, fire
 * `onWake` once (debounced by `cfg.cooldownMs`). Auto-restarts the recognizer
 * when the browser ends a session, and tears down cleanly when
 * disabled/unmounted. Returns `supported` so the UI can hide the control where
 * the API is absent. Tuning (`cfg`) is read live via a ref, so a late config
 * load takes effect without restarting the recognizer.
 */
export function useWakeWord(
  enabled: boolean,
  onWake: () => void,
  cfg: VoiceConfig["wake"] = DEFAULT_VOICE_CONFIG.wake,
) {
  const [supported] = useState(() => getCtor() !== null);
  const [active, setActive] = useState(false);
  const recRef = useRef<SpeechRecognitionLike | null>(null);
  const enabledRef = useRef(enabled);
  const onWakeRef = useRef(onWake);
  const cfgRef = useRef(cfg);
  const cooldownRef = useRef(false);
  onWakeRef.current = onWake;
  cfgRef.current = cfg;

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
        const re = wakeRegex(cfgRef.current.phrase);
        for (let i = ev.resultIndex; i < ev.results.length; i++) {
          const alt = ev.results[i][0];
          if (alt && re.test(alt.transcript.toLowerCase())) {
            cooldownRef.current = true;
            setTimeout(() => {
              cooldownRef.current = false;
            }, cfgRef.current.cooldownMs);
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
        // Browser ends sessions on its own; restart while still enabled.
        if (enabledRef.current) setTimeout(start, cfgRef.current.restartMs);
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

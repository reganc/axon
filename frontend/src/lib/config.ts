// Centralized frontend config. Tuning knobs are read from NEXT_PUBLIC_* env at
// build time (Next.js inlines them) with sane defaults, so nothing operative
// lives as a scattered magic constant. Mirrors the backend's "everything via
// config" rule; set overrides in .env.local and restart `next dev`.
//
// NOTE: these must be referenced as full static `process.env.NEXT_PUBLIC_*`
// literals — dynamic indexing is not inlined by Next.

function num(value: string | undefined, fallback: number): number {
  const n = value != null ? Number(value) : NaN;
  return Number.isFinite(n) ? n : fallback;
}

export const voiceConfig = {
  // Hands-free capture (RMS voice-activity detection): when an armed mic stops.
  vad: {
    autoStopSilenceMs: num(process.env.NEXT_PUBLIC_AXON_VAD_SILENCE_MS, 900),
    maxMs: num(process.env.NEXT_PUBLIC_AXON_VAD_MAX_MS, 12000),
    noSpeechMs: num(process.env.NEXT_PUBLIC_AXON_VAD_NO_SPEECH_MS, 6000),
    silenceThreshold: num(process.env.NEXT_PUBLIC_AXON_VAD_RMS_THRESHOLD, 0.015),
  },
  // Wake word: debounce so one "Jarvis" fires once; recognizer restart gap; and
  // the accepted phrases (pipe-separated alternation, matched on word boundary).
  wake: {
    cooldownMs: num(process.env.NEXT_PUBLIC_AXON_WAKE_COOLDOWN_MS, 2500),
    restartMs: num(process.env.NEXT_PUBLIC_AXON_WAKE_RESTART_MS, 300),
    phrase: process.env.NEXT_PUBLIC_AXON_WAKE_PHRASE ?? "jarvis|jervis|jarvus|jarviss|service",
  },
} as const;

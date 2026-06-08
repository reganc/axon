// Voice tuning config. The operative values are served by the backend at
// GET /voice/config (so all knobs live in the API's .env, not a frontend
// rebuild); these defaults are only the pre-load fallback and must mirror the
// backend defaults in app/config.py. Fetched + cached by useVoiceConfig().

export interface VoiceConfig {
  vad: {
    autoStopSilenceMs: number;
    maxMs: number;
    noSpeechMs: number;
    silenceThreshold: number;
  };
  wake: {
    cooldownMs: number;
    restartMs: number;
    phrase: string;
  };
}

export const DEFAULT_VOICE_CONFIG: VoiceConfig = {
  vad: { autoStopSilenceMs: 900, maxMs: 12000, noSpeechMs: 6000, silenceThreshold: 0.015 },
  wake: { cooldownMs: 2500, restartMs: 300, phrase: "jarvis|jervis|jarvus|jarviss|service" },
};

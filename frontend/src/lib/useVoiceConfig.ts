"use client";
import { useEffect, useState } from "react";
import { getVoiceConfig } from "./api";
import { DEFAULT_VOICE_CONFIG, type VoiceConfig } from "./config";

// Module-level cache so the config is fetched once per page load and shared
// across every consumer; the resolved object keeps a stable identity so hooks
// that depend on it don't churn.
let cache: VoiceConfig | null = null;
let inflight: Promise<VoiceConfig> | null = null;

/** Voice tuning from the backend, falling back to defaults until it loads. */
export function useVoiceConfig(): VoiceConfig {
  const [cfg, setCfg] = useState<VoiceConfig>(cache ?? DEFAULT_VOICE_CONFIG);

  useEffect(() => {
    if (cache) return;
    if (!inflight) {
      inflight = getVoiceConfig()
        .then((c) => (cache = c))
        .catch(() => DEFAULT_VOICE_CONFIG);
    }
    let alive = true;
    inflight.then((c) => {
      if (alive) setCfg(c);
    });
    return () => {
      alive = false;
    };
  }, []);

  return cfg;
}

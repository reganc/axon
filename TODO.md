# AXON — TODO / backlog

Running list of deferred work and feature ideas. Newest at top of each section.

## Voice

- [x] **"Jarvis" wake word to arm the listener.** Done. An always-on browser
  `SpeechRecognition` keyword spotter (`frontend/src/lib/useWakeWord.ts`) listens
  for "jarvis"; on match it barges in on TTS (`stopSpeaking()`) and arms the
  existing mic capture, which now auto-stops on silence (RMS VAD added to
  `useMic`) so it's fully hands-free. The transcript routes through the panel's
  normal answer/interrupt/subject logic. Opt-in via a wake toggle in
  `VoiceControls` (hidden where the API is unsupported, e.g. Firefox).
  Follow-ups if wanted: a real on-device wake-word model (Porcupine/openWakeWord)
  for fewer false fires than browser STT; tunable VAD thresholds in config.

## Self-augmenting library

- [x] **Mine live conversation into the library.** Done. The companion now
  distils a session's learner dialogue back into the graph on WS close.
  `Companion.mine_session` reads the durable conversation, rebuilds a
  learner/tutor transcript from the turns since a per-checkout watermark, and —
  only when the learner actually spoke — runs it through `Ingestion.mine_turns`,
  which shares the batch miner's redact → segment → drop-churn → extract → ground
  → canonicalize pipeline (the one chokepoint). Mined nodes carry
  `source_ref="session-{checkout}#spanN"` so they stay purgeable. The WS fires
  the mine off the hot path (background task in the `finally`) so close returns
  instantly; the watermark + canonicalize idempotency stop a reconnect from
  re-mining settled turns. Also fixed a latent bug: `discuss` (the learner's own
  turns) was never in the library's `_REPLAYABLE` set, so it was silently dropped
  from the durable log despite the StreamEvent contract — now persisted, which
  both restores two-sided card-chat replay and gives the miner the learner's
  words.
  Follow-ups if wanted: also capture run-turn `answer`/`explained_back` text
  (today only `discuss` turns are mined — answers live in the learning store, not
  the conversation log); a config flag to disable session mining; surface a
  "distilled N concepts from this chat" status event to the learner.

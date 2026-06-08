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

- [ ] **Mine live conversation into the library.** Today only companion-generated
  nodes accrete; the learner's own words are stored for replay + mastery but not
  distilled into the graph. Wire a distill pass off the live transcript
  (segment → extract → ground → canonicalize) so dialogue also accretes. The
  miner already exists (`backend/app/seams/ingestion/miner.py`) but is only
  reachable via the batch `/ingest` endpoint, not the companion WS.

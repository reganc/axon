# AXON — TODO / backlog

Running list of deferred work and feature ideas. Newest at top of each section.

## Voice

- [ ] **"Jarvis" wake word to arm the listener.** Add hands-free activation: a
  call/utterance of "jarvis" wakes the listener so the mic input is open and
  ready to accept voice direction — no click on the push-to-talk button. On the
  wake word, cut off any TTS in progress (barge-in via `stopSpeaking()`) and open
  the existing mic capture, then route the transcript through the panel's normal
  answer/interrupt/subject logic. Likely approach: an always-on lightweight
  keyword spotter (browser `SpeechRecognition` continuous mode, or a small
  on-device wake-word model) that, on match, triggers `useMic.start()`. Make it
  opt-in alongside the existing voice toggle, and gate by mic permission.
  Builds on: `frontend/src/lib/useMic.ts`, `frontend/src/lib/voice.ts`,
  `frontend/src/components/VoiceControls.tsx`.

## Self-augmenting library

- [ ] **Mine live conversation into the library.** Today only companion-generated
  nodes accrete; the learner's own words are stored for replay + mastery but not
  distilled into the graph. Wire a distill pass off the live transcript
  (segment → extract → ground → canonicalize) so dialogue also accretes. The
  miner already exists (`backend/app/seams/ingestion/miner.py`) but is only
  reachable via the batch `/ingest` endpoint, not the companion WS.

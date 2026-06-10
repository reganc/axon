// Client side of the self-hosted voice layer: speak() turns the companion's
// `say` text into audio via POST /voice/tts and plays clips strictly in order;
// transcribe() turns a mic clip into text via POST /voice/stt. Voice is
// best-effort — failures are swallowed so a flaky model never breaks the lesson.
import { API_BASE } from "./api";
import { getToken } from "./auth";

function authHeaders(extra?: Record<string, string>): Record<string, string> {
  const token = getToken();
  return { ...(token ? { Authorization: `Bearer ${token}` } : {}), ...extra };
}

// Serialize playback: each say() chains onto the previous so narration never
// overlaps. Barge-in (stopSpeaking) must be *reliable* even though the backend
// keeps streaming `say` events while a turn generates — so a generation counter
// gates every clip. stopSpeaking() bumps it, aborts in-flight fetches, and pauses
// the playing element; any clip whose generation is stale refuses to play, even
// if its fetch only resolves after the stop. Without this, a clip caught
// mid-fetch (current === null, nothing to pause) would sneak through and the
// narrator couldn't be stopped.
let chain: Promise<void> = Promise.resolve();
let current: HTMLAudioElement | null = null;
let generation = 0;
let queued = 0; // outstanding speak() calls in the current generation
const inflight = new Set<AbortController>();

// Lightweight pub/sub so the UI can show a Stop control only while speaking.
let speaking = false;
const speakingListeners = new Set<(v: boolean) => void>();

function setSpeaking(value: boolean): void {
  if (speaking === value) return;
  speaking = value;
  for (const listener of speakingListeners) listener(value);
}

/** Subscribe to narration on/off transitions. Returns an unsubscribe fn and
 *  invokes the listener once immediately with the current state. */
export function subscribeSpeaking(listener: (v: boolean) => void): () => void {
  speakingListeners.add(listener);
  listener(speaking);
  return () => {
    speakingListeners.delete(listener);
  };
}

/** Whether the narrator is currently speaking or has clips queued. */
export function isSpeaking(): boolean {
  return speaking;
}

async function fetchTts(text: string, signal: AbortSignal): Promise<Blob> {
  const res = await fetch(`${API_BASE}/voice/tts`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ text }),
    signal,
  });
  if (!res.ok) throw new Error(`tts ${res.status}`);
  return res.blob();
}

/** Queue `text` to be spoken after anything already speaking. Best-effort.
 *  The TTS fetch starts immediately so synthesis overlaps the previous clip's
 *  playback — only *playback* is serialized. Without the prefetch, every
 *  sentence boundary stalls for a full network+synthesis round trip. */
export function speak(text: string): void {
  const value = text.trim();
  if (!value) return;
  const gen = generation;
  queued += 1;
  setSpeaking(true);
  const controller = new AbortController();
  inflight.add(controller);
  const fetched = fetchTts(value, controller.signal).catch(() => null);
  chain = chain.then(async () => {
    let url: string | null = null;
    try {
      if (gen !== generation) return; // barged in before our turn came up
      const blob = await fetched;
      if (!blob || gen !== generation) return; // fetch failed or barged in
      url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      current = audio;
      await audio.play().catch(() => {});
      if (gen !== generation) {
        audio.pause(); // stopped during play() — make sure it's silent
        return;
      }
      await new Promise<void>((resolve) => {
        audio.onended = () => resolve();
        audio.onerror = () => resolve();
      });
    } catch {
      /* swallow — voice is non-essential; the chain must never reject */
    } finally {
      inflight.delete(controller);
      if (url) URL.revokeObjectURL(url);
      // Bookkeeping belongs to the generation that queued it: stopSpeaking()
      // already zeroed the stale generation's counters, so a late finally from
      // a stopped clip must not decrement (and silence) the new generation.
      if (gen === generation) {
        current = null;
        queued = Math.max(0, queued - 1);
        if (queued === 0) setSpeaking(false);
      }
    }
  });
}

/** Cut off whatever Jarvis is saying and drop the queue (barge-in). Reliable:
 *  aborts pending fetches and invalidates queued clips via the generation bump,
 *  so nothing already in flight sneaks through after the stop. */
export function stopSpeaking(): void {
  generation += 1;
  for (const controller of inflight) controller.abort();
  inflight.clear();
  if (current) {
    current.pause();
    current = null;
  }
  chain = Promise.resolve();
  queued = 0;
  setSpeaking(false);
}

/** Transcribe a recorded mic clip to text via the STT endpoint. */
export async function transcribe(blob: Blob): Promise<string> {
  const ext = blob.type.includes("ogg") ? "ogg" : "webm";
  const form = new FormData();
  form.append("audio", blob, `clip.${ext}`);
  const res = await fetch(`${API_BASE}/voice/stt`, {
    method: "POST",
    headers: authHeaders(),
    body: form,
  });
  if (!res.ok) throw new Error(`stt ${res.status}`);
  const data = (await res.json()) as { text: string };
  return data.text.trim();
}

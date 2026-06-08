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
// overlaps. `current` is the playing element, for barge-in (stopSpeaking).
let chain: Promise<void> = Promise.resolve();
let current: HTMLAudioElement | null = null;

async function fetchTts(text: string): Promise<Blob> {
  const res = await fetch(`${API_BASE}/voice/tts`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ text }),
  });
  if (!res.ok) throw new Error(`tts ${res.status}`);
  return res.blob();
}

/** Queue `text` to be spoken after anything already speaking. Best-effort. */
export function speak(text: string): void {
  const value = text.trim();
  if (!value) return;
  chain = chain.then(async () => {
    let url: string | null = null;
    try {
      url = URL.createObjectURL(await fetchTts(value));
      const audio = new Audio(url);
      current = audio;
      await audio.play().catch(() => {});
      await new Promise<void>((resolve) => {
        audio.onended = () => resolve();
        audio.onerror = () => resolve();
      });
    } catch {
      /* swallow — voice is non-essential */
    } finally {
      if (url) URL.revokeObjectURL(url);
      current = null;
    }
  });
}

/** Cut off whatever Jarvis is saying and drop the queue (barge-in). */
export function stopSpeaking(): void {
  if (current) {
    current.pause();
    current = null;
  }
  chain = Promise.resolve();
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

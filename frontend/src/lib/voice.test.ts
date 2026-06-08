import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { isSpeaking, speak, stopSpeaking, subscribeSpeaking } from "./voice";

// Minimal HTMLAudioElement stand-in: jsdom doesn't implement media playback, and
// we only need to observe whether a clip was ever constructed/played.
class FakeAudio {
  static instances: FakeAudio[] = [];
  paused = false;
  played = false;
  onended: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(public src: string) {
    FakeAudio.instances.push(this);
  }
  play(): Promise<void> {
    this.played = true;
    return Promise.resolve();
  }
  pause(): void {
    this.paused = true;
  }
}

const tick = () => new Promise((r) => setTimeout(r, 0));

beforeEach(() => {
  FakeAudio.instances = [];
  vi.stubGlobal("Audio", FakeAudio);
  // jsdom has no object-URL support — provide just enough for speak().
  globalThis.URL.createObjectURL = vi.fn(() => "blob:fake");
  globalThis.URL.revokeObjectURL = vi.fn();
});

afterEach(async () => {
  stopSpeaking();
  await tick();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("voice barge-in", () => {
  it("flips the speaking signal synchronously on speak/stop", () => {
    globalThis.fetch = vi.fn(() => new Promise(() => {})) as typeof fetch; // never settles
    const seen: boolean[] = [];
    const unsub = subscribeSpeaking((v) => seen.push(v));

    expect(isSpeaking()).toBe(false);
    speak("hello there");
    expect(isSpeaking()).toBe(true);
    stopSpeaking();
    expect(isSpeaking()).toBe(false);

    unsub();
    expect(seen).toEqual([false, true, false]);
  });

  it("aborts the in-flight TTS fetch when stopped", async () => {
    let signal: AbortSignal | undefined;
    globalThis.fetch = vi.fn((_url: string, opts: RequestInit) => {
      signal = opts.signal ?? undefined;
      return new Promise((_resolve, reject) => {
        opts.signal?.addEventListener("abort", () =>
          reject(new DOMException("aborted", "AbortError")),
        );
      });
    }) as unknown as typeof fetch;

    speak("explain backprop");
    await tick(); // let the chain body issue the fetch
    expect(signal).toBeInstanceOf(AbortSignal);
    expect(signal?.aborted).toBe(false);

    stopSpeaking();
    expect(signal?.aborted).toBe(true);
  });

  it("never plays a clip whose fetch resolves after the stop", async () => {
    let resolveFetch!: (blob: Blob) => void;
    globalThis.fetch = vi.fn(
      () =>
        new Promise((resolve) => {
          resolveFetch = (blob) =>
            resolve({ ok: true, blob: () => Promise.resolve(blob) } as Response);
        }),
    ) as unknown as typeof fetch;

    speak("a late clip");
    await tick(); // fetch is now in flight
    stopSpeaking(); // generation bumped while the fetch is still pending
    resolveFetch(new Blob(["x"])); // fetch finishes *after* the stop
    await tick();

    // The stale generation must refuse to construct/play the audio.
    expect(FakeAudio.instances).toHaveLength(0);
    expect(isSpeaking()).toBe(false);
  });
});

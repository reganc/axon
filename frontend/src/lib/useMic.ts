"use client";
import { useCallback, useEffect, useRef, useState } from "react";

interface MicOptions {
  /** Auto-stop after this much trailing silence once speech has been heard. */
  autoStopSilenceMs?: number;
  /** Hard cap on a single capture. */
  maxMs?: number;
  /** Give up if no speech at all is heard within this window. */
  noSpeechMs?: number;
  /** RMS amplitude (0..1) above which a frame counts as speech. */
  silenceThreshold?: number;
}

interface WebkitWindow {
  webkitAudioContext?: typeof AudioContext;
}

/**
 * Microphone capture for the companion. Click to start; stop either by clicking
 * again or — when `autoStop` options are given — automatically once the speaker
 * goes quiet (hands-free, for the wake-word flow). On stop the clip is handed to
 * `onClip`; the mic stream is always released. MediaRecorder yields webm/opus
 * (Chrome) or ogg (Firefox), both of which the STT backend decodes.
 */
export function useMic(onClip: (blob: Blob) => void, opts: MicOptions = {}) {
  const [recording, setRecording] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const vadCleanupRef = useRef<(() => void) | null>(null);

  const autoStop = opts.autoStopSilenceMs != null || opts.maxMs != null;

  const start = useCallback(async () => {
    if (recorderRef.current) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorder.onstop = () => {
        vadCleanupRef.current?.();
        vadCleanupRef.current = null;
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType });
        recorderRef.current = null;
        setRecording(false);
        if (blob.size > 0) onClip(blob);
      };
      recorderRef.current = recorder;
      recorder.start();
      setRecording(true);
      setError(null);
      if (autoStop) {
        vadCleanupRef.current = watchSilence(stream, opts, () => recorder.stop());
      }
    } catch {
      setError("mic unavailable");
      setRecording(false);
    }
  }, [onClip, autoStop, opts]);

  const stop = useCallback(() => {
    recorderRef.current?.stop();
  }, []);

  const toggle = useCallback(() => {
    if (recorderRef.current) stop();
    else void start();
  }, [start, stop]);

  useEffect(() => () => recorderRef.current?.stop(), []);

  return { recording, error, start, stop, toggle };
}

/** Run a lightweight RMS voice-activity loop; calls `onSilence` when the speaker
 *  finishes (or limits are hit). Returns a cleanup that tears down the audio
 *  graph. No external deps — pure Web Audio. */
function watchSilence(
  stream: MediaStream,
  opts: MicOptions,
  onSilence: () => void,
): () => void {
  const Ctx = window.AudioContext ?? (window as unknown as WebkitWindow).webkitAudioContext;
  if (!Ctx) return () => {};
  const ctx = new Ctx();
  const source = ctx.createMediaStreamSource(stream);
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 1024;
  source.connect(analyser);
  const buf = new Float32Array(analyser.fftSize);

  const threshold = opts.silenceThreshold ?? 0.015;
  const silenceMs = opts.autoStopSilenceMs ?? 900;
  const maxMs = opts.maxMs ?? 12000;
  const noSpeechMs = opts.noSpeechMs ?? 5000;

  const startTs = Date.now();
  let lastSpeech = 0;
  let sawSpeech = false;
  let stopped = false;

  const cleanup = () => {
    if (stopped) return;
    stopped = true;
    clearInterval(timer);
    try {
      source.disconnect();
    } catch {
      /* already torn down */
    }
    ctx.close().catch(() => {});
  };

  const timer = setInterval(() => {
    analyser.getFloatTimeDomainData(buf);
    let sum = 0;
    for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
    const rms = Math.sqrt(sum / buf.length);
    const now = Date.now();
    if (rms > threshold) {
      sawSpeech = true;
      lastSpeech = now;
    }
    const elapsed = now - startTs;
    const done =
      elapsed > maxMs ||
      (sawSpeech && now - lastSpeech > silenceMs) ||
      (!sawSpeech && elapsed > noSpeechMs);
    if (done) {
      cleanup();
      onSilence();
    }
  }, 100);

  return cleanup;
}

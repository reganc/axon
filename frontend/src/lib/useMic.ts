"use client";
import { useCallback, useRef, useState } from "react";

/**
 * Push-to-talk microphone capture. Click to start, click to stop; on stop the
 * recorded clip is handed to `onClip`. MediaRecorder produces webm/opus (Chrome)
 * or ogg (Firefox) — the STT backend decodes either. The mic stream is released
 * as soon as recording stops.
 */
export function useMic(onClip: (blob: Blob) => void) {
  const [recording, setRecording] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

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
    } catch {
      setError("mic unavailable");
      setRecording(false);
    }
  }, [onClip]);

  const stop = useCallback(() => {
    recorderRef.current?.stop();
  }, []);

  const toggle = useCallback(() => {
    if (recorderRef.current) stop();
    else void start();
  }, [start, stop]);

  return { recording, error, start, stop, toggle };
}

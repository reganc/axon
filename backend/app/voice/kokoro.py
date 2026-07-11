"""kokoro.py — Kokoro TTS adapter (kokoro-onnx, CPU).

The "Jarvis" voice upgrade: Kokoro-82M's prosody is far more natural than
Piper's, and it ships genuinely British male voices (bm_george, bm_lewis).
Runs on onnxruntime CPU so it never contends with Ollama for the GPU. The
model (~310MB) and voice bank (~27MB) download once into `voice_model_dir`
and cache; nothing heavy loads at import time. Set AXON_TTS_ENGINE=piper to
fall back to the Piper engine without a rebuild.
"""

from __future__ import annotations

import io
import logging
import threading
import wave
from pathlib import Path

import httpx

from ..config import Settings, get_settings

log = logging.getLogger("axon.voice.kokoro")


def _wav_bytes(samples, sample_rate: int) -> bytes:
    """float32 [-1, 1] samples -> mono 16-bit WAV bytes (stdlib only)."""
    import numpy as np

    pcm = np.clip(np.asarray(samples, dtype="float32"), -1.0, 1.0)
    pcm16 = (pcm * 32767.0).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(sample_rate))
        w.writeframes(pcm16.tobytes())
    return buf.getvalue()


class KokoroEngine:
    """Kokoro TTS via kokoro-onnx. Model download is thread-safe + lazy."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._s = settings or get_settings()
        self._lock = threading.Lock()
        # kokoro-onnx shares one onnxruntime InferenceSession; concurrent
        # create() calls on it garble/truncate clips (the frontend prefetches
        # every sentence in parallel, so bursts are the norm). Serialize
        # synthesis — clips queue server-side, prefetch still overlaps playback.
        self._synth_lock = threading.Lock()
        self._kokoro = None

    @property
    def ready(self) -> bool:
        return self._kokoro is not None

    def _ensure(self):
        if self._kokoro is not None:
            return self._kokoro
        with self._lock:
            if self._kokoro is not None:
                return self._kokoro
            d = Path(self._s.voice_model_dir) / "kokoro"
            d.mkdir(parents=True, exist_ok=True)
            model = d / Path(self._s.kokoro_model_url).name
            voices = d / Path(self._s.kokoro_voices_url).name
            for path, url in (
                (model, self._s.kokoro_model_url),
                (voices, self._s.kokoro_voices_url),
            ):
                if path.exists() and path.stat().st_size > 0:
                    continue
                log.info("downloading Kokoro asset %s", url)
                with httpx.stream("GET", url, follow_redirects=True, timeout=600) as r:
                    r.raise_for_status()
                    tmp = path.with_suffix(path.suffix + ".part")
                    with tmp.open("wb") as fh:
                        for chunk in r.iter_bytes():
                            fh.write(chunk)
                    tmp.replace(path)
            from kokoro_onnx import Kokoro  # heavy import — keep it lazy

            self._kokoro = Kokoro(str(model), str(voices))
            return self._kokoro

    def synthesize(self, text: str) -> bytes:
        """Render `text` to WAV bytes. Blocking — run in a threadpool."""
        text = (text or "").strip()
        if not text:
            raise ValueError("empty text")
        kokoro = self._ensure()
        with self._synth_lock:
            samples, sample_rate = kokoro.create(
                text,
                voice=self._s.kokoro_voice,
                speed=self._s.kokoro_speed,
                lang=self._s.kokoro_lang,
            )
        return _wav_bytes(samples, sample_rate)

    def warm(self) -> None:
        """Load the model and run one tiny synthesis so the first real request
        doesn't pay the cold start (~310MB download + session init). Blocking —
        call from a background thread."""
        self.synthesize("Ready.")

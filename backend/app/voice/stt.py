"""stt.py — faster-whisper speech-to-text adapter.

Transcribes a learner's microphone clip (whatever the browser's MediaRecorder
produced — webm/opus, ogg, wav) into text that is injected into the companion's
inbox as an `interrupt`/`answer`. faster-whisper decodes via bundled PyAV, so no
system ffmpeg is required. The model downloads once into `voice_model_dir` and is
cached; loading is lazy and defaults to CPU/int8 to spare the shared GPU.
"""

from __future__ import annotations

import logging
import threading

from ..config import Settings, get_settings

log = logging.getLogger("axon.voice.stt")


class SttEngine:
    """faster-whisper STT. Thread-safe lazy load; blocking transcribe."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._s = settings or get_settings()
        self._model = None  # faster_whisper.WhisperModel, loaded on demand
        self._lock = threading.Lock()

    @property
    def ready(self) -> bool:
        return self._model is not None

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            from faster_whisper import WhisperModel  # heavy import, deferred

            self._model = WhisperModel(
                self._s.stt_model,
                device=self._s.stt_device,
                compute_type=self._s.stt_compute_type,
                download_root=self._s.voice_model_dir,
            )
            log.info(
                "Whisper loaded: %s (%s/%s)",
                self._s.stt_model,
                self._s.stt_device,
                self._s.stt_compute_type,
            )

    def transcribe(self, audio_path: str) -> str:
        """Transcribe an audio file to text. Blocking — run in a threadpool."""
        self._ensure_loaded()
        segments, _info = self._model.transcribe(
            audio_path,
            language=self._s.stt_language,
            beam_size=self._s.stt_beam_size,
            vad_filter=True,  # drop leading/trailing silence from push-to-talk
        )
        return "".join(seg.text for seg in segments).strip()

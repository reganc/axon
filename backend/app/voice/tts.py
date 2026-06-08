"""tts.py — Piper text-to-speech adapter (standalone binary).

Synthesizes the companion's `say` text into a mono 16-bit WAV by invoking the
Piper executable (bundles espeak-ng + onnxruntime — the Python piper package's
piper-phonemize dep has no installable wheel here). The voice model (`.onnx` +
`.onnx.json`) is downloaded once from the public piper-voices repo into
`voice_model_dir` and cached; nothing loads at import time.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
import threading
from pathlib import Path

import httpx

from ..config import Settings, get_settings

log = logging.getLogger("axon.voice.tts")

# Public mirror of Piper voices. A voice id like "en_GB-alan-medium" decomposes
# into <lang>-<name>-<quality> and lives at <family>/<lang>/<name>/<quality>/.
_VOICES_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"


def _voice_relpath(voice: str) -> str:
    """`en_GB-alan-medium` -> `en/en_GB/alan/medium/en_GB-alan-medium`."""
    lang, name, quality = voice.split("-", 2)
    family = lang.split("_", 1)[0]
    return f"{family}/{lang}/{name}/{quality}/{voice}"


class TtsEngine:
    """Piper TTS via subprocess. Model download is thread-safe + lazy."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._s = settings or get_settings()
        self._lock = threading.Lock()
        self._fetched = False

    @property
    def ready(self) -> bool:
        return self._fetched

    def _model_paths(self) -> tuple[Path, Path]:
        d = Path(self._s.voice_model_dir) / "piper"
        stem = self._s.tts_voice
        return d / f"{stem}.onnx", d / f"{stem}.onnx.json"

    def _ensure_model(self) -> tuple[Path, Path]:
        onnx, conf = self._model_paths()
        if self._fetched and onnx.exists() and conf.exists():
            return onnx, conf
        with self._lock:
            onnx.parent.mkdir(parents=True, exist_ok=True)
            rel = _voice_relpath(self._s.tts_voice)
            for path, suffix in ((onnx, ".onnx"), (conf, ".onnx.json")):
                if path.exists() and path.stat().st_size > 0:
                    continue
                url = f"{_VOICES_BASE}/{rel}{suffix}"
                log.info("downloading Piper voice asset %s", url)
                with httpx.stream("GET", url, follow_redirects=True, timeout=120) as r:
                    r.raise_for_status()
                    tmp = path.with_suffix(path.suffix + ".part")
                    with tmp.open("wb") as fh:
                        for chunk in r.iter_bytes():
                            fh.write(chunk)
                    tmp.replace(path)
            self._fetched = True
            return onnx, conf

    def synthesize(self, text: str) -> bytes:
        """Render `text` to WAV bytes. Blocking — run in a threadpool."""
        text = (text or "").strip()
        if not text:
            raise ValueError("empty text")
        onnx, conf = self._ensure_model()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            out_path = tf.name
        try:
            subprocess.run(
                [
                    self._s.tts_piper_bin,
                    "--model",
                    str(onnx),
                    "--config",
                    str(conf),
                    "--output_file",
                    out_path,
                    "--length_scale",
                    str(self._s.tts_length_scale),
                ],
                input=text.encode("utf-8"),
                capture_output=True,
                check=True,
                timeout=60,
            )
            return Path(out_path).read_bytes()
        finally:
            Path(out_path).unlink(missing_ok=True)

"""voice — self-hosted speech I/O for the companion ("Jarvis").

Two local engines, no external services:
- `TtsEngine`  (Piper)          — companion `say` text  -> WAV audio
- `SttEngine`  (faster-whisper) — learner mic audio     -> text

Both are I/O adapters, not seams: they hold no domain logic and are injected at
the router like the LLM gateway. Models lazy-load to `settings.voice_model_dir`
(a mounted volume) on first use, so the image stays slim and rebuilds are fast.
"""

from .stt import SttEngine
from .tts import TtsEngine

__all__ = ["TtsEngine", "SttEngine"]

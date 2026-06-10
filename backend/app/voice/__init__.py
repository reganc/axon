"""voice — self-hosted speech I/O for the companion ("Jarvis").

Three local engines, no external services:
- `KokoroEngine` (kokoro-onnx)  — companion `say` text  -> WAV audio (default)
- `TtsEngine`    (Piper)        — companion `say` text  -> WAV audio (fallback)
- `SttEngine`    (faster-whisper) — learner mic audio   -> text

Both are I/O adapters, not seams: they hold no domain logic and are injected at
the router like the LLM gateway. Models lazy-load to `settings.voice_model_dir`
(a mounted volume) on first use, so the image stays slim and rebuilds are fast.
"""

from .kokoro import KokoroEngine
from .stt import SttEngine
from .tts import TtsEngine

__all__ = ["KokoroEngine", "TtsEngine", "SttEngine"]

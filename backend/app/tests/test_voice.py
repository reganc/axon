"""Voice router tests — engines are faked, so no models download and the GPU is
never touched. Exercises auth, content types, the disabled gate, and STT upload.
"""

from __future__ import annotations

import io
import wave
from pathlib import Path

import pytest

from app.api.routers import voice as voice_router
from app.tests.conftest import token
from app.voice.tts import TtsEngine

USER = "33333333-3333-3333-3333-333333333333"


def _wav_bytes() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(b"\x00\x00" * 100)
    return buf.getvalue()


class _FakeTts:
    ready = True

    def synthesize(self, text: str) -> bytes:
        assert text  # router rejects empties before us
        return _wav_bytes()


class _FakeStt:
    ready = True

    def transcribe(self, path: str) -> str:
        assert path  # a real temp file path was handed to us
        return "hello jarvis"


@pytest.fixture
def fake_engines(monkeypatch):
    monkeypatch.setattr(voice_router, "tts_engine", lambda: _FakeTts())
    monkeypatch.setattr(voice_router, "stt_engine", lambda: _FakeStt())


def test_health_is_unauthenticated_and_does_not_load_models(client):
    r = client.get("/voice/health")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is True
    assert body["tts_ready"] is False and body["stt_ready"] is False


def test_config_serves_tuning_for_the_frontend(client):
    r = client.get("/voice/config")
    assert r.status_code == 200, r.text
    body = r.json()
    # camelCase keys drop straight into the frontend VoiceConfig shape.
    assert set(body["vad"]) == {
        "autoStopSilenceMs",
        "maxMs",
        "noSpeechMs",
        "silenceThreshold",
    }
    assert set(body["wake"]) == {"cooldownMs", "restartMs", "phrase"}
    assert body["vad"]["autoStopSilenceMs"] == 900
    assert "jarvis" in body["wake"]["phrase"]


def test_tts_requires_auth(client):
    r = client.post("/voice/tts", json={"text": "hi"})
    assert r.status_code == 401


def test_tts_returns_wav(client, fake_engines):
    tok = token(client, USER, "learner")
    r = client.post(
        "/voice/tts",
        json={"text": "Good evening. Shall we begin?"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "audio/wav"
    assert r.content[:4] == b"RIFF"


def test_tts_rejects_empty_text(client, fake_engines):
    tok = token(client, USER, "learner")
    r = client.post(
        "/voice/tts",
        json={"text": ""},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 422  # pydantic min_length


def test_stt_transcribes_upload(client, fake_engines):
    tok = token(client, USER, "learner")
    r = client.post(
        "/voice/stt",
        files={"audio": ("clip.webm", b"\x1a\x45\xdf\xa3fake-opus", "audio/webm")},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"text": "hello jarvis"}


def test_tts_engine_passes_pace_flags(monkeypatch, tmp_path):
    """Piper must be invoked with the pace knobs (length_scale slows delivery,
    sentence_silence adds a natural beat between sentences) — these are the fix
    for narration that reads too fast and runs words together."""
    engine = TtsEngine()
    model = tmp_path / "v.onnx"
    conf = tmp_path / "v.onnx.json"
    monkeypatch.setattr(engine, "_ensure_model", lambda: (model, conf))

    captured: dict = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        out = argv[argv.index("--output_file") + 1]
        Path(out).write_bytes(b"RIFFfake")

    monkeypatch.setattr("app.voice.tts.subprocess.run", fake_run)
    assert engine.synthesize("Good evening.") == b"RIFFfake"

    argv = captured["argv"]
    s = voice_router.get_settings()
    assert argv[argv.index("--length_scale") + 1] == str(s.tts_length_scale)
    assert argv[argv.index("--sentence_silence") + 1] == str(s.tts_sentence_silence)
    assert s.tts_length_scale >= 1.0  # never default back into too-fast territory


def test_disabled_returns_503(client, fake_engines, monkeypatch):
    s = voice_router.get_settings()
    monkeypatch.setattr(s, "voice_enabled", False)
    tok = token(client, USER, "learner")
    r = client.post(
        "/voice/tts",
        json={"text": "hi"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 503


def test_tts_engine_selection_follows_config(monkeypatch):
    """AXON_TTS_ENGINE picks the adapter; piper stays one env var away."""
    from app import deps
    from app.voice import KokoroEngine, TtsEngine

    s = deps.get_settings()
    deps.tts_engine.cache_clear()
    monkeypatch.setattr(s, "tts_engine", "kokoro")
    assert isinstance(deps.tts_engine(), KokoroEngine)
    deps.tts_engine.cache_clear()
    monkeypatch.setattr(s, "tts_engine", "piper")
    assert isinstance(deps.tts_engine(), TtsEngine)
    deps.tts_engine.cache_clear()  # don't leak the piper engine to other tests


def test_kokoro_synthesize_renders_wav(monkeypatch):
    """The adapter passes the configured voice/speed/lang to the model and
    encodes its float samples as a mono 16-bit WAV — no model download."""
    from app.voice.kokoro import KokoroEngine

    captured = {}

    class _FakeKokoro:
        def create(self, text, voice, speed, lang):
            captured.update(text=text, voice=voice, speed=speed, lang=lang)
            return [0.0, 0.5, -0.5, 1.0, -1.0], 24000

    engine = KokoroEngine()
    monkeypatch.setattr(engine, "_ensure", lambda: _FakeKokoro())
    wav = engine.synthesize("Good evening. Shall we begin?")

    s = voice_router.get_settings()
    assert captured["voice"] == s.kokoro_voice
    assert captured["speed"] == s.kokoro_speed
    assert captured["lang"] == s.kokoro_lang
    assert wav[:4] == b"RIFF"
    with wave.open(io.BytesIO(wav)) as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getframerate() == 24000
        assert w.getnframes() == 5

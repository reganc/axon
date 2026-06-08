"""Voice router tests — engines are faked, so no models download and the GPU is
never touched. Exercises auth, content types, the disabled gate, and STT upload.
"""

from __future__ import annotations

import io
import wave

import pytest

from app.api.routers import voice as voice_router
from app.tests.conftest import token

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

"""voice router — self-hosted TTS/STT for the companion.

- POST /voice/tts   {text}        -> audio/wav   (Jarvis speaks)
- POST /voice/stt   <audio file>  -> {text}      (learner speaks)
- GET  /voice/health              -> readiness   (unauthenticated probe)

Heavy model work runs in a threadpool so the event loop is never blocked. Engines
lazy-load their models on first call; /voice/health never triggers a load.
"""

from __future__ import annotations

import os
import tempfile

from fastapi import APIRouter, Depends, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ...config import get_settings
from ...deps import stt_engine, tts_engine
from ...errors import DomainError
from ...ports import Principal
from ..security import require_perm

router = APIRouter(prefix="/voice", tags=["voice"])

_MAX_TTS_CHARS = 4000
_MAX_STT_BYTES = 25 * 1024 * 1024  # 25 MB — a push-to-talk clip, not a podcast


class VoiceDisabledError(DomainError):
    status = 503


class PayloadTooLargeError(DomainError):
    status = 413


def _require_enabled() -> None:
    if not get_settings().voice_enabled:
        raise VoiceDisabledError("voice is disabled (AXON_VOICE_ENABLED=false)")


class TtsReq(BaseModel):
    text: str = Field(..., min_length=1, max_length=_MAX_TTS_CHARS)


class SttResp(BaseModel):
    text: str


@router.post("/tts")
async def tts(
    req: TtsReq, _: Principal = Depends(require_perm("graph:read"))
) -> Response:
    _require_enabled()
    audio = await run_in_threadpool(tts_engine().synthesize, req.text)
    return Response(
        content=audio,
        media_type="audio/wav",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/stt", response_model=SttResp)
async def stt(
    audio: UploadFile,
    _: Principal = Depends(require_perm("graph:read")),
) -> SttResp:
    _require_enabled()
    data = await audio.read(_MAX_STT_BYTES + 1)
    if len(data) > _MAX_STT_BYTES:
        raise PayloadTooLargeError("audio too large")
    suffix = os.path.splitext(audio.filename or "")[1] or ".webm"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        tmp.write(data)
        tmp.flush()
        tmp.close()
        text = await run_in_threadpool(stt_engine().transcribe, tmp.name)
    finally:
        os.unlink(tmp.name)
    return SttResp(text=text)


@router.get("/health")
async def voice_health() -> dict:
    s = get_settings()
    return {
        "enabled": s.voice_enabled,
        "tts_voice": s.tts_voice,
        "tts_ready": tts_engine().ready,
        "stt_model": s.stt_model,
        "stt_device": s.stt_device,
        "stt_ready": stt_engine().ready,
    }

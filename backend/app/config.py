"""config.py — all runtime knobs via env (prefix AXON_). No hardcoded secrets."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AXON_",
        env_file=".env",
        extra="ignore",
        protected_namespaces=(),  # we use model_reason / model_cheap fields
    )

    # app
    app_name: str = "axon"
    env: str = "dev"
    api_port: int = (
        8100  # container-internal bind; host maps via AXON_API_PORT (default 4100)
    )
    cors_origins: list[str] = ["http://localhost:4101", "http://localhost:3000"]
    # Optional regex of additional allowed origins, for reaching the app over a
    # LAN / Tailscale IP without pinning each one. Passed to CORSMiddleware's
    # allow_origin_regex; the specific matched origin is echoed back, so this is
    # credential-safe (unlike a "*" wildcard). Empty = strict list-only default.
    cors_origin_regex: str = ""

    # data / cache
    database_url: str = "postgresql+asyncpg://axon:axon@db:5432/axon"
    redis_url: str = "redis://cache:6379/0"
    db_use_nullpool: bool = (
        False  # tests set this: no pooled conns to cross event loops
    )

    # auth (real impl in Phase 1, lifted from carecore/havencore)
    jwt_secret: str = "change-me-dev-only"
    jwt_alg: str = "HS256"
    jwt_expire_min: int = 720

    # inference (Phase 2)
    # fast/local tier -> the centralized llm-app gateway (OpenAI-compatible).
    # Every app on this host shares it; use the stable "default" alias and NEVER
    # hardcode a concrete local model/gguf tag. See CLAUDE.md > LLM access.
    llm_base_url: str = "http://host.docker.internal:8030/v1"
    llm_api_key: str = ""  # Bearer token for the gateway (set in .env)
    llm_model: str = "default"  # gateway resolves the alias to the active model
    # embeddings -> the same box's Ollama (the gateway has no embeddings endpoint)
    ollama_base_url: str = "http://host.docker.internal:11434"
    ollama_embed_model: str = "nomic-embed-text"  # 768-dim
    embed_dim: int = 768
    embed_backend: str = (
        "ollama"  # "ollama" (real, falls back) | "deterministic" (offline)
    )
    # Degrade fast when Ollama embeddings are wedged (e.g. the embed model can't
    # load alongside the chat model). A short per-call timeout makes a single
    # call fall back quickly; the breaker then skips the primary entirely after a
    # run of failures so a whole seed/session doesn't pay the timeout per node.
    embed_timeout: float = 5.0  # seconds per embed call before falling back
    embed_breaker_threshold: int = 3  # consecutive failures before tripping (<=0 off)
    embed_breaker_cooldown: float = 60.0  # seconds to skip primary while tripped
    # reason tier -> Anthropic API (off-box, opt-in via key)
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"

    # canonicalization thresholds (tune empirically once generation flows)
    canon_merge_threshold: float = 0.92
    canon_related_threshold: float = 0.80

    # companion / agents (Phase 2)
    llm_reason_fallback_to_fast: bool = (
        True  # no Anthropic key -> route reason via Ollama
    )
    companion_reuse_threshold: float = (
        0.85  # Tutor: search hit >= this -> reuse, don't generate
    )
    companion_confidence_floor: float = (
        0.55  # Researcher: below -> flag, don't publish as fact
    )
    companion_max_steps: int = 8  # cap nodes generated per turn
    companion_generate_concurrency: int = (
        3  # nodes materialized in parallel per turn (generate ∥ ground pipeline)
    )
    librarian_merge_threshold: float = (
        0.93  # background dedup of near-duplicate AI nodes
    )
    librarian_interval_sec: float = (
        300.0  # seconds between background curation passes (the worker loop)
    )

    # transcript miner (Phase 3)
    miner_segment_threshold: float = (
        0.6  # consecutive-message cosine below -> topic boundary
    )
    miner_min_span_chars: int = (
        140  # drop spans shorter than this (debugging churn / dead-ends)
    )
    miner_max_spans: int = 40  # safety cap on spans mined per source

    # cost control (specs/06): tiered routing + budgets + circuit breaker
    model_reason: str = "claude-sonnet-4-6"  # accuracy-critical cloud reasoning
    model_cheap: str = "claude-haiku-4-5"  # cheap cloud tasks (extract/classify/plan)
    model_ground: str = "claude-haiku-4-5"  # research grounding — Haiku is plenty
    # Where the fast tier (node drafts + streamed narration/explanations) runs.
    # "local" = the shared 14B gateway (free, ~24s/draft). "cloud" = model_cheap
    # (Haiku, ~2s) — far faster at trivial cost; requires an Anthropic key. The
    # budget breaker still degrades cloud fast-work to local when over budget.
    fast_tier: str = "local"  # "local" | "cloud"
    escalate_floor: float = (
        0.6  # local draft below this confidence -> escalate to cloud
    )
    budget_session_usd: float = 0.50
    budget_user_daily_usd: float = 2.00
    budget_global_daily_usd: float = 50.00
    budget_soft_fraction: float = 0.8  # degrade to local at this fraction of a budget
    batch_enabled: bool = (
        True  # route latency-tolerant cloud work through the Batch API
    )

    # voice I/O (self-hosted, no external services): Piper TTS + faster-whisper
    # STT. Models lazy-load to voice_model_dir (a mounted volume) on first use.
    # Whisper defaults to CPU/int8 so it never contends with the shared Ollama
    # model on the host GPU; flip stt_device="cuda" if you have headroom.
    voice_enabled: bool = True
    voice_model_dir: str = "/models/voice"
    tts_voice: str = "en_US-ryan-medium"  # Piper voice: natural American male
    tts_piper_bin: str = "/opt/piper/piper"  # standalone binary (set in Dockerfile)
    tts_length_scale: float = 0.95  # >1 slower/calmer, <1 faster; <0.9 slurs words
    stt_model: str = "base.en"  # faster-whisper size: tiny.en|base.en|small.en
    stt_device: str = "cpu"  # "cpu" | "cuda"
    stt_compute_type: str = "int8"  # "int8" (cpu) | "float16" (cuda)
    stt_beam_size: int = 1
    stt_language: str = "en"
    # client-side voice tuning, served to the frontend via GET /voice/config so
    # all tuning lives in one place (this .env), not a frontend rebuild.
    vad_silence_ms: int = 900  # stop capture after this much trailing silence
    vad_max_ms: int = 12000  # hard cap on one hands-free capture
    vad_no_speech_ms: int = 6000  # bail if nothing is said after arming
    vad_rms_threshold: float = 0.015  # amplitude (0..1) that counts as speech
    wake_cooldown_ms: int = 2500  # debounce: one "Jarvis" fires once
    wake_restart_ms: int = 300  # gap before restarting the recognizer
    wake_phrase: str = "jarvis|jervis|jarvus|jarviss|service"  # accepted, |-sep


@lru_cache
def get_settings() -> Settings:
    return Settings()

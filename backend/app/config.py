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

    # inference gateway (Phase 2)
    ollama_base_url: str = (
        "http://host.docker.internal:11434"  # Ollama on the comet host
    )
    ollama_chat_model: str = "llama3.1:8b"
    ollama_embed_model: str = "nomic-embed-text"
    anthropic_api_key: str = ""
    anthropic_model: str = (
        ""  # set AXON_ANTHROPIC_MODEL to your chosen model id (reason tier)
    )
    embed_dim: int = 768
    embed_backend: str = (
        "ollama"  # "ollama" (real, falls back) | "deterministic" (offline)
    )

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
    librarian_merge_threshold: float = (
        0.93  # background dedup of near-duplicate AI nodes
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
    model_reason: str = "claude-sonnet-4-6"  # default cloud reasoning model
    model_cheap: str = "claude-haiku-4-5"  # cheap cloud tasks (extract/classify)
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


@lru_cache
def get_settings() -> Settings:
    return Settings()

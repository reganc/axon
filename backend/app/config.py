"""config.py — all runtime knobs via env (prefix AXON_). No hardcoded secrets."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AXON_", env_file=".env", extra="ignore"
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


@lru_cache
def get_settings() -> Settings:
    return Settings()

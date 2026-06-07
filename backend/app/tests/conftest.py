"""Shared test fixtures.

Defaults target the dev compose db on the host (localhost:4102) and the local
Ollama. Override via the usual AXON_ env vars. Integration tests skip cleanly
when Postgres or Ollama isn't reachable, so `pytest` works in any environment.
"""

from __future__ import annotations

import asyncio
import os

import pytest

# Env must be set before app.config's settings are first read (it is lru_cached).
os.environ.setdefault(
    "AXON_DATABASE_URL", "postgresql+asyncpg://axon:change-me@localhost:4102/axon"
)
os.environ.setdefault("AXON_OLLAMA_BASE_URL", "http://localhost:11434")
os.environ.setdefault("AXON_JWT_SECRET", "test-secret-not-for-prod")
os.environ.setdefault("AXON_DB_USE_NULLPOOL", "true")

import httpx  # noqa: E402
import sqlalchemy as sa  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

DB_URL = os.environ["AXON_DATABASE_URL"]
OLLAMA_URL = os.environ["AXON_OLLAMA_BASE_URL"]

FOUNDATIONS_SPINE_ID = "69f5cb6a-449a-518d-8a5b-6b182a1ac320"


def _db_reachable() -> bool:
    async def ping() -> bool:
        engine = create_async_engine(DB_URL)
        try:
            async with engine.connect() as conn:
                await conn.execute(sa.text("SELECT 1"))
            return True
        finally:
            await engine.dispose()

    try:
        return asyncio.run(ping())
    except Exception:
        return False


def _ollama_reachable() -> bool:
    try:
        return httpx.get(f"{OLLAMA_URL}/api/tags", timeout=3).status_code == 200
    except Exception:
        return False


DB_AVAILABLE = _db_reachable()
OLLAMA_AVAILABLE = _ollama_reachable()

requires_db = pytest.mark.skipif(not DB_AVAILABLE, reason="Postgres not reachable")
requires_ollama = pytest.mark.skipif(
    not OLLAMA_AVAILABLE, reason="Ollama not reachable (real-embedding test)"
)


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


def token(client, user_id: str, role: str) -> str:
    r = client.post("/auth/token", json={"user_id": user_id, "role": role})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def auth_header(client, user_id: str, role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token(client, user_id, role)}"}

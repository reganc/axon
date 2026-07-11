"""Shared test fixtures.

Defaults target the dev compose db on the host (localhost:4102) and the local
Ollama. Override via the usual AXON_ env vars. Integration tests skip cleanly
when Postgres or Ollama isn't reachable, so `pytest` works in any environment.
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

import pytest

# The suite is DESTRUCTIVE — fixtures TRUNCATE the graph/overlay tables. It must
# never touch the app's live database. Derive a dedicated `*_test` sibling from
# whatever DB the app is configured for (or AXON_TEST_DATABASE_URL when given)
# and force it into the environment *before* app.config's lru_cached settings are
# first read, so the TestClient app, the seam fixtures, and the raw-SQL helpers
# all share the one isolated DB.
_DEFAULT_DB = "postgresql+asyncpg://axon:change-me@localhost:4102/axon"


def _derive_test_url(url: str) -> str:
    m = re.match(r"(?P<prefix>.*/)(?P<db>[^/?]+)(?P<query>\?.*)?$", url)
    if not m:
        return url
    db = m.group("db")
    if not db.endswith("_test"):
        db = f"{db}_test"
    return f"{m.group('prefix')}{db}{m.group('query') or ''}"


_TEST_DB_URL = os.environ.get("AXON_TEST_DATABASE_URL") or _derive_test_url(
    os.environ.get("AXON_DATABASE_URL", _DEFAULT_DB)
)
os.environ["AXON_DATABASE_URL"] = _TEST_DB_URL
os.environ.setdefault("AXON_OLLAMA_BASE_URL", "http://localhost:11434")
os.environ.setdefault("AXON_JWT_SECRET", "test-secret-not-for-prod")
os.environ.setdefault("AXON_DB_USE_NULLPOOL", "true")
# Deployment behaviour knobs a developer may have in .env (e.g. fast_tier=cloud)
# must not leak into unit tests that assert code defaults. Scrub them from the
# test process; tests that exercise a non-default set it explicitly.
os.environ.pop("AXON_FAST_TIER", None)
# Never warm the real TTS model inside a test run — voice tests assert that
# nothing loads models except an explicit synthesize call.
os.environ["AXON_TTS_WARM_ON_START"] = "false"

import httpx  # noqa: E402
import sqlalchemy as sa  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

DB_URL = os.environ["AXON_DATABASE_URL"]
OLLAMA_URL = os.environ["AXON_OLLAMA_BASE_URL"]


def _bootstrap_test_db() -> None:
    """Create the dedicated test database and apply the schema if it's missing,
    so `pytest` works out of the box without ever provisioning live data."""
    import asyncpg

    dsn = DB_URL.replace("postgresql+asyncpg://", "postgresql://")
    db_name = re.match(r".*/([^/?]+)(\?.*)?$", dsn).group(1)
    maint = re.sub(r"/[^/?]+(\?.*)?$", "/postgres", dsn, count=1)
    # artifacts/ sits beside backend/ in a repo checkout (CI) but is mounted at
    # /app/artifacts inside the api container — walk up until we find it so the
    # path is layout-independent.
    schema_path = next(
        (
            p / "artifacts" / "schema.sql"
            for p in Path(__file__).resolve().parents
            if (p / "artifacts" / "schema.sql").is_file()
        ),
        None,
    )

    async def go() -> None:
        admin = await asyncpg.connect(maint)
        try:
            if not await admin.fetchval(
                "SELECT 1 FROM pg_database WHERE datname = $1", db_name
            ):
                await admin.execute(f'CREATE DATABASE "{db_name}"')
        finally:
            await admin.close()
        conn = await asyncpg.connect(dsn)
        try:
            empty = await conn.fetchval("SELECT to_regclass('public.canonical_nodes')")
            if empty is None:
                if schema_path is None:
                    raise RuntimeError(
                        "artifacts/schema.sql not found; cannot provision the test DB"
                    )
                await conn.execute(schema_path.read_text())
        finally:
            await conn.close()

    asyncio.run(go())


try:
    _bootstrap_test_db()
except OSError:
    # DB server unreachable (no Postgres in this environment) -> DB tests skip
    # via DB_AVAILABLE below. A reachable-but-unprovisionable DB raises instead,
    # so the failure is loud rather than a cascade of "relation does not exist".
    pass

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


# --------------------------------------------------------------------------
# Seeding + real-seam helpers shared by Phase 1 and Phase 2 integration tests
# --------------------------------------------------------------------------

import json  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import pytest_asyncio  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

SEED_AUTHOR = "aaaaaaaa-0000-0000-0000-000000000001"


async def reset_graph() -> None:
    """Truncate graph + overlay tables — keeps the suite repeatable on a
    persistent dev DB (first-load insert counts stay deterministic)."""
    # Hard stop: this TRUNCATEs (CASCADE). Never run it against a live DB. The
    # header forces a `*_test` database; this is the belt-and-braces check in
    # case AXON_DATABASE_URL is ever pointed somewhere destructive.
    db_name = DB_URL.rsplit("/", 1)[-1].split("?")[0]
    if not db_name.endswith("_test"):
        raise RuntimeError(
            f"refusing to TRUNCATE non-test database {db_name!r}; point "
            "AXON_TEST_DATABASE_URL (or AXON_DATABASE_URL) at a *_test database"
        )
    engine = create_async_engine(DB_URL, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                sa.text(
                    "TRUNCATE sources, canonical_nodes, spines, users "
                    "RESTART IDENTITY CASCADE"
                )
            )
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def seeded(client):
    """Reset, then load the LeCun seed once. Returns the first-load report."""
    asyncio.run(reset_graph())
    r = client.post(
        "/ingest/seed",
        json={"path": "artifacts/lecun_seed_graph.json"},
        headers=auth_header(client, SEED_AUTHOR, "author"),
    )
    assert r.status_code == 200, r.text
    return r.json()


@pytest_asyncio.fixture
async def seams():
    """Real content/library/ingestion/learning on a NullPool engine bound to the
    current test's event loop, with a real (Ollama) embedder."""
    from app.embeddings import build_embedder
    from app.seams.content import Content
    from app.seams.ingestion import Ingestion
    from app.seams.learning import Learning
    from app.seams.library import Library

    engine = create_async_engine(DB_URL, poolclass=NullPool)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    embedder = build_embedder()
    content = Content(sm)
    ns = SimpleNamespace(
        sm=sm,
        embedder=embedder,
        content=content,
        library=Library(sm, embedder),
        ingestion=Ingestion(content, embedder),
        learning=Learning(sm),
    )
    try:
        yield ns
    finally:
        await engine.dispose()


def _between(text: str, start: str, end: str) -> str:
    i = text.find(start)
    if i < 0:
        return ""
    i += len(start)
    j = text.find(end, i)
    return text[i : (j if j >= 0 else None)].strip()


def scripted_handler(plan: list[str], confidence: float = 0.8):
    """A FakeLLM handler: scripts plan/generate/ground replies off the prompt tag."""

    def handler(msgs):
        user = next((m.content for m in msgs if m.role == "user"), "")
        if "TASK: plan" in user:
            return json.dumps({"steps": plan})
        if "TASK: generate_node" in user:
            concept = _between(user, "Concept:", "\n") or "concept"
            return json.dumps(
                {
                    "hook": f"Hook: why does {concept} matter?",
                    "body": f"A focused explanation of {concept}.",
                    "recall_prompts": [f"What is {concept}?"],
                }
            )
        if "TASK: ground" in user:
            return json.dumps(
                {"confidence": confidence, "source_ref": "test://grounded"}
            )
        if "TASK: explain" in user:
            concept = _between(user, "Concept:", "\n") or "concept"
            return (
                f"Let's dig into {concept}. The core intuition is simple. "
                f"Here is a concrete example. And this is why it matters."
            )
        if "TASK: discuss" in user:
            return (
                "Good follow-up. Here is the heart of it. "
                "And that connects to the bigger picture."
            )
        if "TASK: extract_concept" in user:
            # A follow-up prefixed "NEW:" surfaces a fresh concept (auto-accrete);
            # anything else is treated as a clarification (stays ephemeral talk).
            q = _between(user, "Learner asked:", "\n")
            if q.startswith("NEW:"):
                title = q[len("NEW:") :].strip()
                return json.dumps(
                    {
                        "new_concept": True,
                        "title": title,
                        "hook": f"Why does {title} matter?",
                        "body": f"A short take on {title}.",
                    }
                )
            return json.dumps({"new_concept": False})
        if "TASK: find_media" in user:
            # A mix of resolvable ("good") and dead ("bad") candidates so tests can
            # assert the validation gate drops the bad ones.
            return json.dumps(
                {
                    "videos": [
                        "https://www.youtube.com/watch?v=GOODvid",
                        "https://www.youtube.com/watch?v=BADvid",
                    ],
                    "links": [
                        {"title": "Good ref", "url": "https://good.example/ref"},
                        {"title": "Dead ref", "url": "https://bad.example/404"},
                    ],
                    "images": ["https://good.example/pic.png"],
                }
            )
        if "TASK: diagram" in user:
            return "graph TD; A[Input] --> B[Conv]; B --> C[Pool]"
        if "TASK: materials" in user:
            concept = _between(user, "Concept:", "\n") or "concept"
            return json.dumps(
                {
                    "summary": f"The essentials of {concept} in a few sentences.",
                    "analogy": f"{concept} is like a familiar everyday thing.",
                    "questions": [f"What breaks if {concept} is wrong?"],
                }
            )
        return "OK"

    return handler


async def scalar(query: str, **params):
    engine = create_async_engine(DB_URL, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            return (await conn.execute(sa.text(query), params)).scalar()
    finally:
        await engine.dispose()


async def exec_sql(query: str, **params) -> None:
    """Run a write statement and commit it."""
    engine = create_async_engine(DB_URL, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.execute(sa.text(query), params)
    finally:
        await engine.dispose()


def make_companion(seams, plan: list[str], confidence: float = 0.8, dive_cache=None):
    """A Companion wired to real seams but a scripted (deterministic) LLM.

    `dive_cache` defaults to None (no caching) so tests stay hermetic — pass a
    `MemoryDiveCache` to exercise the cached deep-dive path explicitly."""
    from app.seams.companion import Companion
    from app.seams.companion.llm import LLMGateway

    gateway = LLMGateway.scripted(scripted_handler(plan, confidence), seams.embedder)
    return Companion(
        llm=gateway,
        library=seams.library,
        ingestion=seams.ingestion,
        content=seams.content,
        learning=seams.learning,
        dive_cache=dive_cache,
    )


def make_miner(seams, handler):
    """An Ingestion wired to real content/embedder but a scripted LLM (for mine())."""
    from app.seams.companion.llm import LLMGateway
    from app.seams.ingestion import Ingestion

    gateway = LLMGateway.scripted(handler, seams.embedder)
    return Ingestion(content=seams.content, embedder=seams.embedder, llm=gateway)

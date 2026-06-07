"""Phase 1 integration — the seed-load / search / checkout / canonicalize substrate.

Requires Postgres (the dev compose db). Skips cleanly when it isn't reachable.
The seed is loaded once per session via the `seeded` fixture.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.embeddings import build_embedder
from app.errors import ConflictError
from app.ports import CandidateNode, NodeIn
from app.seams.content import Content
from app.seams.ingestion import Ingestion

from .conftest import (
    DB_URL,
    FOUNDATIONS_SPINE_ID,
    auth_header,
    requires_db,
    requires_ollama,
)

pytestmark = requires_db

AUTHOR = str(uuid4())
LEARNER = str(uuid4())
CNN_WEIGHT_SHARING_KEY = "cnn-weight-sharing"


# -- helpers ------------------------------------------------------------------


async def _scalar(query: str, **params):
    engine = create_async_engine(DB_URL, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            return (await conn.execute(sa.text(query), params)).scalar()
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def seam():
    """A Content + Ingestion pair on a fresh engine bound to the current test's
    event loop (avoids cross-loop reuse of the app's global engine)."""
    engine = create_async_engine(DB_URL, poolclass=NullPool)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    content = Content(sm)
    ingestion = Ingestion(content, build_embedder())
    try:
        yield content, ingestion
    finally:
        await engine.dispose()


# `seeded` (session-scoped reset + seed) lives in conftest, shared with Phase 2.


# -- seed loading -------------------------------------------------------------


def test_seed_counts(seeded):
    # 31 nodes / 44 edges since Phase 5 re-anchored the pilot on person-yann-lecun
    # (+1 person node, +3 'about' edges); 3 spines unchanged.
    assert seeded == {"nodes": 31, "edges": 44, "spines": 3, "merged": 0, "redacted": 0}


async def test_seed_is_idempotent(client, seeded):
    again = client.post(
        "/ingest/seed",
        json={"path": "artifacts/lecun_seed_graph.json"},
        headers=auth_header(client, AUTHOR, "author"),
    )
    assert again.status_code == 200
    assert again.json() == {
        "nodes": 0,
        "edges": 0,
        "spines": 0,
        "merged": 0,
        "redacted": 0,
    }
    # the LeCun seed nodes are unchanged (count by source so anchors/AI nodes
    # added by other tests don't interfere): 30 concepts + 1 person = 31
    assert (
        await _scalar(
            "SELECT count(*) FROM canonical_nodes WHERE source_ref LIKE 'lecun/%'"
        )
        == 31
    )


async def test_all_nodes_have_768d_embeddings(seeded):
    assert (
        await _scalar(
            "SELECT count(*) FROM canonical_nodes WHERE source_ref LIKE 'lecun/%'"
        )
        == 31
    )
    # every *seed-loaded* node is embedded (nodes CRUD'd directly elsewhere may
    # legitimately have no embedding until the canonicalizer computes one)
    assert (
        await _scalar(
            "SELECT count(*) FROM canonical_nodes WHERE source_ref LIKE 'lecun/%' AND embedding IS NULL"
        )
        == 0
    )
    dims = await _scalar(
        "SELECT vector_dims(embedding) FROM canonical_nodes WHERE source_ref LIKE 'lecun/%' LIMIT 1"
    )
    assert dims == 768


# -- graph reads --------------------------------------------------------------


def test_list_spines_returns_seeded_three(client, seeded):
    r = client.get("/graph/spines", headers=auth_header(client, LEARNER, "learner"))
    assert r.status_code == 200, r.text
    spines = r.json()
    titles = {s["title"] for s in spines}
    assert {"The Foundations", "The Conviction", "The Contrarian Bet"} <= titles
    foundations = next(s for s in spines if s["title"] == "The Foundations")
    assert foundations["node_count"] == 10


def test_get_foundations_spine_ordered(client, seeded):
    r = client.get(
        f"/graph/spines/{FOUNDATIONS_SPINE_ID}",
        headers=auth_header(client, LEARNER, "learner"),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["nodes"]) == 10
    returned = [n["id"] for n in body["nodes"]]
    assert returned == _foundations_sequence()


def _foundations_sequence() -> list[str]:
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    data = json.loads((root / "artifacts" / "lecun_seed_graph.json").read_text())
    spine = next(s for s in data["spines"] if s["id"] == FOUNDATIONS_SPINE_ID)
    return spine["node_sequence"]


# -- checkout / overlay -------------------------------------------------------


def test_checkout_materializes_overlay(client, seeded):
    co = client.post(
        "/library/checkout",
        json={"spine_id": FOUNDATIONS_SPINE_ID},
        headers=auth_header(client, LEARNER, "learner"),
    )
    assert co.status_code == 200, co.text
    checkout_id = co.json()["id"]

    overlay = client.get(
        f"/library/checkout/{checkout_id}",
        headers=auth_header(client, LEARNER, "learner"),
    )
    assert overlay.status_code == 200
    states = overlay.json()
    assert len(states) == 10
    assert all(s["mastery"] == 0.0 for s in states)


# -- invariants: locked nodes, canonicalize merge -----------------------------


async def test_locked_node_cannot_be_overwritten(seeded, seam):
    content, _ = seam
    with pytest.raises(ConflictError):
        await content.upsert_node(
            NodeIn(
                canonical_key=CNN_WEIGHT_SHARING_KEY,
                title="hijack",
                body="overwrite attempt",
            )
        )


async def test_canonicalize_merges_into_locked_neighbor(seeded, seam):
    _, ingestion = seam
    before = await _scalar("SELECT count(*) FROM canonical_nodes")
    # Title normalizes to the existing key -> exact-key MERGE against the locked node.
    result = await ingestion.canonicalize(
        CandidateNode(
            title="CNN weight sharing",
            hook="Why reuse the same filter across the image?",
            body="A convolution applies one shared kernel everywhere, so weights are tied.",
        )
    )
    after = await _scalar("SELECT count(*) FROM canonical_nodes")
    assert result.action == "merged"
    assert result.neighbor_id is not None
    assert after == before  # no duplicate created


# -- RBAC ---------------------------------------------------------------------


def test_learner_denied_graph_write(client, seeded):
    r = client.post(
        "/ingest/seed",
        json={"path": "artifacts/lecun_seed_graph.json"},
        headers=auth_header(client, LEARNER, "learner"),
    )
    assert r.status_code == 403


# -- semantic search (needs real embeddings) ----------------------------------


@requires_ollama
def test_search_convolution_surfaces_cnn_cluster(client, seeded):
    r = client.get(
        "/library/search",
        params={"q": "convolutional neural network filters and weight sharing", "k": 5},
        headers=auth_header(client, LEARNER, "learner"),
    )
    assert r.status_code == 200, r.text
    results = r.json()
    assert results, "search returned nothing"
    titles = " ".join(s["node"]["title"].lower() for s in results)
    keys = " ".join(s["node"]["canonical_key"] for s in results)
    assert "cnn" in keys or "convolu" in titles
    # scores are descending similarities in [0, 1]
    scores = [s["score"] for s in results]
    assert scores == sorted(scores, reverse=True)
    assert all(0.0 <= s <= 1.0 for s in scores)

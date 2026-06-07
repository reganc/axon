"""Librarian worker — background dedup (DB integration)."""

from __future__ import annotations

from uuid import uuid4

from app.workers.librarian import run_once

from .conftest import requires_db, scalar

pytestmark = requires_db


async def test_librarian_merges_two_near_duplicate_ai_nodes(seeded, seams):
    # Two AI nodes with identical embeddings (same body text) — seeded directly so
    # they bypass the live canonicalizer that would have merged them on creation.
    emb = await seams.embedder.embed(
        "librarian dedup probe — a unique throwaway concept body"
    )
    a_id, b_id = str(uuid4()), str(uuid4())
    for nid, key in ((a_id, "lib-dup-a"), (b_id, "lib-dup-b")):
        await seams.content.seed_node(
            {
                "id": nid,
                "canonical_key": key,
                "title": key,
                "origin": "ai_generated",
                "locked": False,
                "confidence": 0.6,
                "hook": "h",
                "body": "b",
            },
            emb,
        )

    keys = "('lib-dup-a','lib-dup-b')"
    assert (
        await scalar(
            f"SELECT count(*) FROM canonical_nodes WHERE canonical_key IN {keys}"
        )
        == 2
    )

    report = await run_once(seams.sm)
    assert report["merged"] >= 1

    assert (
        await scalar(
            f"SELECT count(*) FROM canonical_nodes WHERE canonical_key IN {keys}"
        )
        == 1
    )

"""companion seam — the Tutor event stream (DB + scripted LLM)."""

from __future__ import annotations

import asyncio
from uuid import uuid4

from app.ports import CandidateNode
from app.seams.ingestion import normalize_key

from .conftest import make_companion, requires_db, scalar

pytestmark = requires_db


async def _free_checkout(seams, subject: str):
    return await seams.library.checkout(uuid4(), None, subject)


async def test_run_turn_streams_and_persists_generated_node(seeded, seams):
    subject = "Quantum tunnelling in semiconductor junctions"
    comp = make_companion(seams, plan=[subject], confidence=0.82)
    checkout = await _free_checkout(seams, subject)

    events = [e async for e in comp.run_turn(checkout.id, subject)]
    types = [e.type for e in events]

    assert "say" in types
    assert "node.create" in types
    assert "node.update" in types  # gap -> canonicalize reconciliation
    assert types[-1] == "done"

    # the generated node landed in the library, queryable, grounded by the Researcher
    node = await seams.content.get_node_by_key(normalize_key(subject))
    assert node is not None
    assert node.origin in ("ai_generated", "ai_extended")
    assert abs(node.confidence - 0.82) < 0.02
    # (semantic-ranking quality of search is covered by the Ollama-gated Phase-1 test)


async def test_known_subject_reuses_without_generating(seeded, seams):
    # titles that normalize to seeded canonical keys -> Tutor reuses, never generates
    plan = ["The convolutional network", "Backpropagation"]
    comp = make_companion(seams, plan=plan)
    checkout = await _free_checkout(seams, "convolutional networks")

    before = await scalar("SELECT count(*) FROM canonical_nodes")
    events = [e async for e in comp.run_turn(checkout.id, "convolutional networks")]
    after = await scalar("SELECT count(*) FROM canonical_nodes")

    assert after == before  # nothing new generated
    assert any(e.type == "node.create" and e.data.get("reused") for e in events)
    assert not any(e.type == "node.update" for e in events)


async def test_interrupt_visibly_changes_the_stream(seeded, seams):
    comp = make_companion(seams, plan=["The convolutional network"])
    checkout = await _free_checkout(seams, "CNNs")
    inbox: asyncio.Queue = asyncio.Queue()
    inbox.put_nowait({"type": "interrupt", "text": "Backpropagation"})

    events = [e async for e in comp.run_turn(checkout.id, "CNNs", inbox)]
    says = [e.data.get("text", "") for e in events if e.type == "say"]
    assert any("Backpropagation" in t for t in says)


async def test_generated_node_never_overwrites_locked_anchor(seeded, seams):
    before = await seams.content.get_node_by_key("cnn-weight-sharing")
    comp = make_companion(seams, plan=["CNN weight sharing"])
    checkout = await _free_checkout(seams, "CNNs")

    async for _ in comp.run_turn(checkout.id, "CNNs"):
        pass

    after = await seams.content.get_node_by_key("cnn-weight-sharing")
    assert after.locked is True
    assert after.version == before.version
    assert after.body == before.body


async def test_unlocked_duplicate_merges_not_duplicates(seeded, seams):
    title = "Synthetic companion test concept alpha"
    first = await seams.ingestion.canonicalize(
        CandidateNode(
            title=title, hook="h1", body="b1", origin="ai_generated", confidence=0.7
        )
    )
    assert first.action == "created"

    before = await scalar("SELECT count(*) FROM canonical_nodes")
    second = await seams.ingestion.canonicalize(
        CandidateNode(
            title=title, hook="h2", body="b2", origin="ai_generated", confidence=0.7
        )
    )
    after = await scalar("SELECT count(*) FROM canonical_nodes")

    assert second.action == "merged"
    assert after == before
    assert second.node.version > first.node.version
    assert second.node.origin == "ai_extended"


async def test_pull_thread_spawns_rabbit_hole(seeded, seams):
    comp = make_companion(seams, plan=[])
    anchor = await seams.content.get_node_by_key("the-convolutional-network")
    checkout = await _free_checkout(seams, "rabbit hole")

    events = [e async for e in comp.pull_thread(checkout.id, anchor.id)]
    types = [e.type for e in events]
    assert "node.create" in types
    assert types[-1] == "done"
    assert any(
        e.type == "edge.create" and e.data["edge"]["type"] == "rabbit_hole"
        for e in events
    )


async def test_explain_node_streams_and_persists_materials(seeded, seams):
    comp = make_companion(seams, plan=[])
    node = await seams.content.get_node_by_key("the-convolutional-network")
    checkout = await _free_checkout(seams, "deep dive")

    before = await scalar("SELECT count(*) FROM canonical_nodes")
    events = [e async for e in comp.explain_node(checkout.id, node.id)]
    after = await scalar("SELECT count(*) FROM canonical_nodes")

    # 1) the explanation streams as several say events pinned to the opened card
    says = [e for e in events if e.type == "say"]
    assert len(says) >= 2
    assert all(e.data.get("node_id") == str(node.id) for e in says)

    # 2) materials persist into the library as new nodes + edges back to the card
    assert after > before
    assert any(e.type == "node.update" for e in events)
    assert any(e.type == "edge.create" for e in events)
    assert events[-1].type == "done"

    # a follow-up question landed as a `question` node linked `about` the concept
    summary = await seams.content.get_node_by_key(
        normalize_key(f"Key points: {node.title}")
    )
    assert summary is not None and summary.kind == "artifact"


async def test_explain_node_strips_citation_markers(seeded, seams):
    from app.seams.companion import _flush_sentences, _sanitize

    assert _sanitize("Backprop is the chain rule [W2] in disguise [L1].") == (
        "Backprop is the chain rule  in disguise ."
    )
    remaining, sentences = _flush_sentences("One sentence. A second one. tail")
    assert sentences == ["One sentence.", "A second one."]
    assert remaining.strip() == "tail"

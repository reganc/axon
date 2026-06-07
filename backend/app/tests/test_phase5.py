"""Phase 5 foundation — polymorphic node kinds, attributes, new edge types.

Backward-compatible data-model slice: existing nodes are untouched; new kinds and
edge types are accepted; type-specific `attributes` round-trip.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.errors import ConflictError
from app.ports import NodeIn

from .conftest import make_companion, requires_db, scalar

pytestmark = requires_db


async def test_existing_concept_seed_nodes_carry_empty_attributes(seeded, seams):
    # the original concept/apply seed nodes are unchanged by the migration
    # (the person hub legitimately carries attributes — that's Phase 5 §7)
    non_empty = await scalar(
        "SELECT count(*) FROM canonical_nodes WHERE source_ref LIKE 'lecun/%' "
        "AND kind IN ('concept', 'apply') AND attributes <> '{}'"
    )
    assert non_empty == 0
    node = await seams.content.get_node_by_key("jepa")
    assert node.attributes == {}
    assert node.kind == "concept"


async def test_lecun_pilot_is_person_anchored(seeded, seams):
    person = await seams.content.get_node_by_key("person-yann-lecun")
    assert person.kind == "person"
    assert person.attributes["country"] == "France"
    assert "convolutional networks" in person.attributes["notable_for"]
    # the three signature nodes point at the person via 'about'
    sub = await seams.content.get_subgraph([person.id], depth=1)
    about = [e for e in sub.edges if e.type == "about" and e.dst_node == person.id]
    assert len(about) == 3


async def test_anchor_seed_loads_idempotently_and_surfaces(seeded, seams):
    report = await seams.ingestion.ingest_seed("artifacts/anchor_seed.json")
    assert report.nodes == 9  # 6 questions + 3 people
    assert report.edges == 3
    again = await seams.ingestion.ingest_seed("artifacts/anchor_seed.json")
    assert again.nodes == 0 and again.edges == 0  # idempotent

    q = await seams.content.get_node_by_key("anchor-what-is-intelligence")
    assert q.kind == "question" and q.body is None and q.attributes["status"] == "open"
    p = await seams.content.get_node_by_key("anchor-person-alan-turing")
    assert p.kind == "person" and p.attributes["born"] == 1912

    keys = {n.canonical_key for n in await seams.library.entry_points(limit=100)}
    assert "anchor-what-is-intelligence" in keys
    assert "anchor-person-alan-turing" in keys


async def test_person_node_with_attributes_roundtrips(seeded, seams):
    person = NodeIn(
        canonical_key="person-test-lecun",
        title="Test — Yann LeCun",
        kind="person",
        body="Pioneer of convolutional networks.",
        origin="authored",
        attributes={
            "born": 1960,
            "country": "France",
            "affiliations": ["Bell Labs", "NYU", "Meta"],
        },
    )
    created = await seams.content.upsert_node(person)
    assert created.kind == "person"
    assert created.attributes["affiliations"] == ["Bell Labs", "NYU", "Meta"]

    fetched = await seams.content.get_node_by_key("person-test-lecun")
    assert fetched.kind == "person"
    assert fetched.attributes == {
        "born": 1960,
        "country": "France",
        "affiliations": ["Bell Labs", "NYU", "Meta"],
    }


async def test_question_node_has_no_answer_body(seeded, seams):
    q = NodeIn(
        canonical_key="question-why-do-cnns-generalize",
        title="Why do CNNs generalize so well?",
        kind="question",
        hook="A curiosity gap with no settled answer — open it and the companion builds one.",
        body=None,
        attributes={"status": "open", "difficulty": "hard"},
    )
    created = await seams.content.upsert_node(q)
    assert created.kind == "question"
    assert created.body is None
    assert created.attributes["status"] == "open"


async def test_new_edge_types_are_accepted(seeded, seams):
    jepa = await seams.content.get_node_by_key("jepa")
    person = await seams.content.upsert_node(
        NodeIn(
            canonical_key="person-edge-test",
            title="A Person",
            kind="person",
            origin="authored",
        )
    )
    edge = await seams.content.add_edge(jepa.id, person.id, "about", origin="authored")
    assert edge.type == "about"

    sub = await seams.content.get_subgraph([jepa.id], depth=1)
    assert any(e.type == "about" and e.dst_node == person.id for e in sub.edges)


async def test_entry_points_surface_question_and_person_anchors(seeded, seams):
    await seams.content.upsert_node(
        NodeIn(
            canonical_key="question-what-is-intelligence",
            title="What is intelligence?",
            kind="question",
            hook="The question LeCun's whole career circles.",
            origin="authored",
        )
    )
    await seams.content.upsert_node(
        NodeIn(
            canonical_key="person-entry-anchor",
            title="An Anchor Person",
            kind="person",
            origin="authored",
        )
    )
    eps = await seams.library.entry_points(limit=100)
    keys = {n.canonical_key for n in eps}
    assert "question-what-is-intelligence" in keys
    assert "person-entry-anchor" in keys
    # only anchor kinds are surfaced (the 30 concept seed nodes are not)
    assert all(n.kind in ("question", "person") for n in eps)


async def test_type_aware_search_filters_by_kind(seeded, seams):
    await seams.ingestion.ingest_seed("artifacts/anchor_seed.json")
    persons = await seams.library.search(
        "influential scientist and thinker", k=5, kinds=["person"]
    )
    assert persons and all(s.node.kind == "person" for s in persons)
    questions = await seams.library.search(
        "a deep open question", k=5, kinds=["question"]
    )
    assert questions and all(s.node.kind == "question" for s in questions)


async def test_explore_question_builds_answer_subgraph(seeded, seams):
    question = await seams.content.upsert_node(
        NodeIn(
            canonical_key="question-how-do-cnns-see",
            title="How do CNNs see?",
            kind="question",
            hook="What lets a grid of numbers recognize a cat?",
            origin="authored",
        )
    )
    comp = make_companion(
        seams, plan=["Convolution as feature detection", "Pooling and invariance"]
    )
    checkout = await seams.library.checkout(uuid4(), None, "cnn question")

    events = [e async for e in comp.explore_question(checkout.id, question.id)]
    types = [e.type for e in events]
    assert "node.create" in types
    assert types[-1] == "done"

    # the generated concepts are linked back to the question with `answers` edges
    sub = await seams.content.get_subgraph([question.id], depth=1)
    answers = [
        e for e in sub.edges if e.type == "answers" and e.dst_node == question.id
    ]
    assert len(answers) >= 1


async def test_locked_invariant_still_holds_for_polymorphic_nodes(seeded, seams):
    # locking applies regardless of kind — a locked person node can't be overwritten
    await seams.content.upsert_node(
        NodeIn(
            canonical_key="person-locked-test",
            title="Locked Person",
            kind="person",
            locked=True,
            origin="authored",
        )
    )
    with pytest.raises(ConflictError):
        await seams.content.upsert_node(
            NodeIn(canonical_key="person-locked-test", title="hijack", kind="person")
        )

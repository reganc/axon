"""Phase 5 foundation — polymorphic node kinds, attributes, new edge types.

Backward-compatible data-model slice: existing nodes are untouched; new kinds and
edge types are accepted; type-specific `attributes` round-trip.
"""

from __future__ import annotations

import pytest

from app.errors import ConflictError
from app.ports import NodeIn

from .conftest import requires_db, scalar

pytestmark = requires_db


async def test_existing_authored_nodes_carry_empty_attributes(seeded, seams):
    # the 30 LeCun seed nodes are unchanged and now have attributes = {}
    non_empty = await scalar(
        "SELECT count(*) FROM canonical_nodes WHERE origin = 'authored' AND attributes <> '{}'"
    )
    assert non_empty == 0
    node = await seams.content.get_node_by_key("jepa")
    assert node.attributes == {}
    assert node.kind == "concept"


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

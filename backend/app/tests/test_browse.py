"""Browse facets — the derived taxonomy lens (Phase 5 §8)."""
from __future__ import annotations

from app.ports import NodeIn

from .conftest import requires_db

pytestmark = requires_db


def _type_count(facets, label: str) -> int:
    for g in facets.groups:
        if g.dimension == "type":
            for v in g.values:
                if v.label == label:
                    return v.node_count
    return 0


async def test_facets_are_derived_from_graph_contents(seeded, seams):
    f = await seams.library.facets()
    dims = {g.dimension for g in f.groups}
    assert {"type", "origin", "subject", "theme"} <= dims
    assert f.node_total >= 31

    type_labels = {v.label for g in f.groups if g.dimension == "type" for v in g.values}
    assert "concept" in type_labels and "person" in type_labels

    subjects = {v.label for g in f.groups if g.dimension == "subject" for v in g.values}
    assert "Understanding Yann LeCun" in subjects

    # theme clusters non-person nodes under their nearest person hub
    themes = [v for g in f.groups if g.dimension == "theme" for v in g.values]
    assert themes and all(v.node_count > 0 for v in themes)


async def test_facets_change_when_nodes_are_added(seeded, seams):
    before = await seams.library.facets()
    base_skill = _type_count(before, "skill")

    await seams.content.upsert_node(
        NodeIn(
            canonical_key="skill-first-principles-thinking",
            title="First-principles thinking",
            kind="skill",
            origin="authored",
        )
    )

    after = await seams.library.facets()
    # the lens reflects the new node — proving it's a view, not a stored tree
    assert _type_count(after, "skill") == base_skill + 1
    assert after.node_total == before.node_total + 1

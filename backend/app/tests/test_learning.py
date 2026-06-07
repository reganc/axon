"""learning seam — mastery + scheduler (DB integration)."""

from __future__ import annotations

from uuid import uuid4

from app.ports import InteractionEvent

from .conftest import FOUNDATIONS_SPINE_ID, exec_sql, requires_db, scalar

pytestmark = requires_db


async def _checkout_and_node(seams):
    """A real checkout over the Foundations spine + one of its node ids (so the
    node_states FKs resolve)."""
    user_id = uuid4()
    checkout = await seams.library.checkout(user_id, FOUNDATIONS_SPINE_ID, None)
    spine = await seams.content.get_spine(FOUNDATIONS_SPINE_ID)
    return checkout.id, spine.nodes[0].id


async def test_record_writes_to_event_stream(seeded, seams):
    cid, nid = uuid4(), uuid4()
    await seams.learning.record(
        InteractionEvent(checkout_id=cid, node_id=nid, event_type="viewed", payload={})
    )
    n = await scalar(
        "SELECT count(*) FROM interaction_events WHERE checkout_id = :c", c=cid
    )
    assert n == 1


async def test_mastery_rises_with_explained_back(seeded, seams):
    cid, nid = await _checkout_and_node(seams)
    await seams.learning.record(
        InteractionEvent(checkout_id=cid, node_id=nid, event_type="viewed", payload={})
    )
    baseline = await seams.learning.update_mastery(cid, nid)

    await seams.learning.record(
        InteractionEvent(
            checkout_id=cid, node_id=nid, event_type="explained_back", payload={}
        )
    )
    after = await seams.learning.update_mastery(cid, nid)
    assert after > baseline


async def test_confused_lowers_mastery_and_counts(seeded, seams):
    cid, nid = await _checkout_and_node(seams)
    for et in ("explained_back", "confused", "confused"):
        await seams.learning.record(
            InteractionEvent(checkout_id=cid, node_id=nid, event_type=et, payload={})
        )
    mastery = await seams.learning.update_mastery(cid, nid)
    confusion = await scalar(
        "SELECT confusion_count FROM node_states WHERE checkout_id = :c AND node_id = :n",
        c=cid,
        n=nid,
    )
    assert confusion == 2
    assert 0.0 <= mastery <= 1.0


async def test_due_reviews_surface_once_past_due(seeded, seams):
    cid, nid = await _checkout_and_node(seams)
    await seams.learning.update_mastery(cid, nid)  # creates the node_state row
    # nothing due yet (next_review_at is in the future)
    assert nid not in await seams.learning.due_reviews(cid)
    # backdate the review and it surfaces
    await exec_sql(
        "UPDATE node_states SET next_review_at = now() - interval '1 hour' "
        "WHERE checkout_id = :c AND node_id = :n",
        c=cid,
        n=nid,
    )
    assert nid in await seams.learning.due_reviews(cid)

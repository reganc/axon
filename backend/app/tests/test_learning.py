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


async def test_learner_context_reads_focus_weak_strong(seeded, seams):
    """The prompt-conditioning read: focal mastery + confusions, plus the
    checkout's weak/strong nodes with the focal node excluded."""
    user_id = uuid4()
    checkout = await seams.library.checkout(user_id, FOUNDATIONS_SPINE_ID, None)
    spine = await seams.content.get_spine(FOUNDATIONS_SPINE_ID)
    cid = checkout.id
    focal, weak, strong = (spine.nodes[i].id for i in range(3))

    async def feed(nid, *event_types, payload=None):
        for et in event_types:
            await seams.learning.record(
                InteractionEvent(
                    checkout_id=cid, node_id=nid, event_type=et, payload=payload or {}
                )
            )
        await seams.learning.update_mastery(cid, nid)

    await feed(focal, "viewed", "confused")  # 0.03 - 0.25 -> 0.0, 1 confusion
    await feed(weak, "confused", "confused")  # -> 0.0, 2 confusions
    await feed(
        strong,
        "explained_back",
        "hook_engaged",
        "rabbit_hole_followed",
        "asked_question",
        "viewed",
        "deep_dive",
        "discussed",
    )  # -> 0.73

    ctx = await seams.learning.learner_context(cid, focal)
    assert ctx.focus_mastery == 0.0
    assert ctx.focus_confusions == 1
    assert any(nm.node_id == weak for nm in ctx.weakest)
    assert any(nm.node_id == strong and nm.mastery >= 0.7 for nm in ctx.strongest)
    # the focal node never appears in its own context lists
    assert all(nm.node_id != focal for nm in [*ctx.weakest, *ctx.strongest])

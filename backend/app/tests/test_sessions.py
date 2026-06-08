"""Durable conversations + session list."""

from __future__ import annotations

from uuid import uuid4

from .conftest import FOUNDATIONS_SPINE_ID, requires_db

pytestmark = requires_db


async def test_record_and_replay_conversation(seeded, seams):
    user = uuid4()
    co = await seams.library.checkout(user, None, "test session")

    await seams.library.record_event(co.id, "say", {"text": "hello"})
    await seams.library.record_event(
        co.id, "status", {"detail": "transient"}
    )  # not stored
    await seams.library.record_event(
        co.id, "node.create", {"temp_id": "t1", "node": {"title": "X"}}
    )

    convo = await seams.library.get_conversation(co.id)
    assert [e.type for e in convo] == ["say", "node.create"]  # status dropped, in order
    assert convo[0].data["text"] == "hello"


async def test_list_checkouts_returns_sessions_with_summary(seeded, seams):
    user = uuid4()
    spine_co = await seams.library.checkout(
        user, FOUNDATIONS_SPINE_ID, "Understanding Yann LeCun"
    )
    free_co = await seams.library.checkout(user, None, "free roam")
    await seams.library.record_event(spine_co.id, "say", {"text": "a"})
    await seams.library.record_event(spine_co.id, "say", {"text": "b"})

    sessions = await seams.library.list_checkouts(user)
    ids = {s.id for s in sessions}
    assert spine_co.id in ids and free_co.id in ids

    summary = next(s for s in sessions if s.id == spine_co.id)
    assert summary.spine_title == "The Foundations"
    assert summary.message_count == 2
    # most-recently-active first: the session with recorded activity leads
    assert sessions[0].id == spine_co.id


async def test_other_users_sessions_are_not_listed(seeded, seams):
    mine, theirs = uuid4(), uuid4()
    my_co = await seams.library.checkout(mine, None, "mine")
    await seams.library.checkout(theirs, None, "theirs")
    sessions = await seams.library.list_checkouts(mine)
    assert {s.id for s in sessions} == {my_co.id}

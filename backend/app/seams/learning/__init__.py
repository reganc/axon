"""learning seam — mastery model + spaced-repetition scheduler.

Phase 2. Mastery is a fuzzy 0..1 signal *inferred from dialogue events*, never a
quiz score: events accrete into `interaction_events` (a Timescale hypertable) and
`update_mastery` recomputes the node's mastery from them, then schedules the next
review (SM-2-style intervals). Due reviews surface later as Tutor `ask` events —
never as a blocking test.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ...ports import InteractionEvent
from ...tables import interaction_events, node_states

# Per-event contribution to mastery. recall_attempt is split by payload.correct.
_EVENT_WEIGHTS = {
    "explained_back": 0.40,
    "recall_attempt_correct": 0.30,
    "hook_engaged": 0.10,
    "asked_question": 0.05,
    "rabbit_hole_followed": 0.05,
    "viewed": 0.03,
    "confused": -0.25,
    "recall_attempt_incorrect": -0.15,
}

# Mastery band -> next-review interval (SM-2-flavoured, coarse).
_REVIEW_INTERVALS = [
    (0.85, timedelta(days=7)),
    (0.60, timedelta(days=2)),
    (0.30, timedelta(hours=8)),
]
_DEFAULT_INTERVAL = timedelta(minutes=10)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _event_signal(event_type: str, payload: dict) -> float:
    if event_type == "recall_attempt":
        key = (
            "recall_attempt_correct"
            if payload.get("correct")
            else "recall_attempt_incorrect"
        )
        return _EVENT_WEIGHTS[key]
    return _EVENT_WEIGHTS.get(event_type, 0.0)


def _schedule(mastery: float) -> datetime:
    for floor, interval in _REVIEW_INTERVALS:
        if mastery >= floor:
            return _now() + interval
    return _now() + _DEFAULT_INTERVAL


class Learning:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sm = sessionmaker

    async def record(self, event: InteractionEvent) -> None:
        values = {
            "checkout_id": UUID(str(event.checkout_id)),
            "node_id": UUID(str(event.node_id)) if event.node_id else None,
            "event_type": event.event_type,
            "payload": event.payload,
        }
        if event.ts is not None:
            values["ts"] = event.ts
        async with self._sm() as session, session.begin():
            await session.execute(interaction_events.insert().values(**values))

    async def update_mastery(self, checkout_id: UUID, node_id: UUID) -> float:
        cid, nid = UUID(str(checkout_id)), UUID(str(node_id))
        async with self._sm() as session, session.begin():
            rows = (
                await session.execute(
                    select(
                        interaction_events.c.event_type, interaction_events.c.payload
                    ).where(
                        (interaction_events.c.checkout_id == cid)
                        & (interaction_events.c.node_id == nid)
                    )
                )
            ).all()

            score = 0.0
            confusion = 0
            explained = False
            for r in rows:
                et = r._mapping[interaction_events.c.event_type]
                payload = r._mapping[interaction_events.c.payload] or {}
                score += _event_signal(et, payload)
                if et == "confused":
                    confusion += 1
                if et == "explained_back":
                    explained = True

            mastery = max(0.0, min(1.0, score))
            await session.execute(
                pg_insert(node_states)
                .values(
                    checkout_id=cid,
                    node_id=nid,
                    mastery=mastery,
                    explained_back=explained,
                    confusion_count=confusion,
                    last_seen=_now(),
                    next_review_at=_schedule(mastery),
                )
                .on_conflict_do_update(
                    index_elements=["checkout_id", "node_id"],
                    set_={
                        "mastery": mastery,
                        "explained_back": explained,
                        "confusion_count": confusion,
                        "last_seen": _now(),
                        "next_review_at": _schedule(mastery),
                    },
                )
            )
            return mastery

    async def due_reviews(self, checkout_id: UUID) -> list[UUID]:
        cid = UUID(str(checkout_id))
        async with self._sm() as session:
            rows = (
                await session.execute(
                    select(node_states.c.node_id)
                    .where(
                        (node_states.c.checkout_id == cid)
                        & (node_states.c.next_review_at.is_not(None))
                        & (node_states.c.next_review_at <= func.now())
                    )
                    .order_by(node_states.c.next_review_at)
                )
            ).all()
        return [r._mapping[node_states.c.node_id] for r in rows]


# Back-compat alias for deps.py during the stub→real swap.
StubLearning = Learning

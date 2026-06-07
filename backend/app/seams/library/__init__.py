"""library seam — semantic search, coverage, checkout + overlay.

Phase 1. Search is pgvector cosine over `canonical_nodes.embedding`. A checkout
instantiates a per-learner overlay: a `checkouts` row plus lazily-materialized
`node_states` (mastery 0) for the spine's nodes. Free-roam checkout (no spine) is
allowed and materializes nothing.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ...embeddings import Embedder
from ...errors import NotFoundError
from ...ports import Checkout, Coverage, NodeState, ScoredNode
from ...tables import canonical_nodes, checkouts, node_states, spines, users
from ..content import _NODE_COLS, _row_to_node


class Library:
    def __init__(
        self, sessionmaker: async_sessionmaker[AsyncSession], embedder: Embedder
    ) -> None:
        self._sm = sessionmaker
        self._embed = embedder

    async def search(self, query: str, k: int = 10) -> list[ScoredNode]:
        qvec = await self._embed.embed(query)
        distance = canonical_nodes.c.embedding.cosine_distance(qvec).label("distance")
        async with self._sm() as session:
            rows = (
                await session.execute(
                    select(*_NODE_COLS, distance)
                    .where(canonical_nodes.c.embedding.is_not(None))
                    .order_by(distance)
                    .limit(k)
                )
            ).all()
        # cosine distance in [0, 2]; similarity score = 1 - distance, clamped to [0, 1]
        return [
            ScoredNode(
                node=_row_to_node(r),
                score=max(0.0, 1.0 - float(r._mapping["distance"])),
            )
            for r in rows
        ]

    async def coverage(self, subject: str) -> Coverage:
        """What the library already holds for a subject (the spines' nodes). Gap
        detection is the Phase-2 Planner's job; Phase 1 reports `have`, no gaps."""
        async with self._sm() as session:
            rows = (
                await session.execute(
                    select(spines.c.node_sequence).where(spines.c.subject == subject)
                )
            ).all()
        have: list[UUID] = []
        seen: set[UUID] = set()
        for r in rows:
            for nid in r._mapping[spines.c.node_sequence]:
                u = UUID(nid)
                if u not in seen:
                    seen.add(u)
                    have.append(u)
        return Coverage(subject=subject, have=have, gaps=[])

    async def checkout(
        self, user_id: UUID, spine_id: UUID | None, subject: str | None
    ) -> Checkout:
        uid = UUID(str(user_id))
        sid = UUID(str(spine_id)) if spine_id else None
        async with self._sm() as session, session.begin():
            # ensure the user exists (dev: tokens may be issued for fresh ids)
            await session.execute(
                pg_insert(users)
                .values(id=uid)
                .on_conflict_do_nothing(index_elements=["id"])
            )

            seq: list[str] = []
            if sid is not None:
                spine = (
                    await session.execute(
                        select(spines.c.node_sequence).where(spines.c.id == sid)
                    )
                ).first()
                if spine is None:
                    raise NotFoundError(f"spine {sid} not found")
                seq = spine._mapping[spines.c.node_sequence]

            co = (
                await session.execute(
                    checkouts.insert()
                    .values(user_id=uid, spine_id=sid, subject=subject)
                    .returning(
                        checkouts.c.id,
                        checkouts.c.user_id,
                        checkouts.c.spine_id,
                        checkouts.c.subject,
                    )
                )
            ).first()
            checkout_id = co._mapping[checkouts.c.id]

            if seq:
                await session.execute(
                    pg_insert(node_states)
                    .values(
                        [{"checkout_id": checkout_id, "node_id": UUID(n)} for n in seq]
                    )
                    .on_conflict_do_nothing(index_elements=["checkout_id", "node_id"])
                )

            return Checkout(
                id=checkout_id,
                user_id=co._mapping[checkouts.c.user_id],
                spine_id=co._mapping[checkouts.c.spine_id],
                subject=co._mapping[checkouts.c.subject],
            )

    async def merge_companion_memory(self, checkout_id: UUID, patch: dict) -> None:
        """Shallow-merge into checkouts.companion_memory (the Tutor's memory of
        this learner for this subject)."""
        cid = UUID(str(checkout_id))
        async with self._sm() as session, session.begin():
            row = (
                await session.execute(
                    select(checkouts.c.companion_memory).where(checkouts.c.id == cid)
                )
            ).first()
            if row is None:
                return
            memory = dict(row._mapping[checkouts.c.companion_memory] or {})
            memory.update(patch)
            await session.execute(
                checkouts.update()
                .where(checkouts.c.id == cid)
                .values(companion_memory=memory)
            )

    async def checkout_owner(self, checkout_id: UUID) -> UUID | None:
        """Owner of a checkout, for `checkout:read:self` enforcement at the router."""
        async with self._sm() as session:
            row = (
                await session.execute(
                    select(checkouts.c.user_id).where(
                        checkouts.c.id == UUID(str(checkout_id))
                    )
                )
            ).first()
        return row._mapping[checkouts.c.user_id] if row else None

    async def overlay_state(self, checkout_id: UUID) -> list[NodeState]:
        cid = UUID(str(checkout_id))
        async with self._sm() as session:
            rows = (
                await session.execute(
                    select(
                        node_states.c.checkout_id,
                        node_states.c.node_id,
                        node_states.c.mastery,
                        node_states.c.next_review_at,
                        node_states.c.learner_notes,
                    ).where(node_states.c.checkout_id == cid)
                )
            ).all()
        return [
            NodeState(
                checkout_id=r._mapping[node_states.c.checkout_id],
                node_id=r._mapping[node_states.c.node_id],
                mastery=r._mapping[node_states.c.mastery],
                next_review_at=r._mapping[node_states.c.next_review_at],
                learner_notes=r._mapping[node_states.c.learner_notes],
            )
            for r in rows
        ]


# Back-compat alias for deps.py during the stub→real swap.
StubLibrary = Library

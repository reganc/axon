"""content seam — canonical graph CRUD (nodes, edges, spines, sources).

Phase 1. This seam owns every write to the canonical graph tables. The locked
invariant lives here: an authored/`locked` node may not be overwritten through
normal CRUD — only the canonicalizer adds *around* it (lateral edges, neighbors),
never through its body. `upsert_node` enforces that; the `seed_*` methods are the
one path that inserts authored content verbatim (with explicit ids so the seed's
edges/spines resolve).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ...errors import ConflictError, NotFoundError
from ...ports import (
    Edge,
    EdgeType,
    Node,
    NodeIn,
    SpineSummary,
    SpineWithNodes,
    Subgraph,
)
from ...tables import canonical_nodes, edges, sources, spines

# Columns returned as a Node DTO (embedding is deliberately excluded — it must
# never ride along in an API response).
_NODE_COLS = [
    canonical_nodes.c.id,
    canonical_nodes.c.canonical_key,
    canonical_nodes.c.title,
    canonical_nodes.c.kind,
    canonical_nodes.c.hook,
    canonical_nodes.c.body,
    canonical_nodes.c.apply_prompt,
    canonical_nodes.c.recall_prompts,
    canonical_nodes.c.mastery_criteria,
    canonical_nodes.c.depth_level,
    canonical_nodes.c.origin,
    canonical_nodes.c.locked,
    canonical_nodes.c.source_ref,
    canonical_nodes.c.confidence,
    canonical_nodes.c.version,
    canonical_nodes.c.attributes,
]


def _row_to_node(row) -> Node:
    return Node(**{c.name: row._mapping[c] for c in _NODE_COLS})


class Content:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sm = sessionmaker

    # -- writes ---------------------------------------------------------------

    async def upsert_node(
        self, node: NodeIn, *, embedding: list[float] | None = None
    ) -> Node:
        """Create-or-update a node by canonical_key. Rejects updates to locked nodes."""
        async with self._sm() as session, session.begin():
            existing = (
                await session.execute(
                    select(canonical_nodes.c.id, canonical_nodes.c.locked).where(
                        canonical_nodes.c.canonical_key == node.canonical_key
                    )
                )
            ).first()

            values = (
                node.model_dump()
            )  # exactly the NodeIn columns; DB defaults the rest
            if embedding is not None:
                values["embedding"] = embedding

            if existing is None:
                row = (
                    await session.execute(
                        canonical_nodes.insert().values(**values).returning(*_NODE_COLS)
                    )
                ).first()
                return _row_to_node(row)

            if existing._mapping[canonical_nodes.c.locked]:
                raise ConflictError(
                    f"node {node.canonical_key!r} is locked; CRUD may not overwrite it"
                )
            row = (
                await session.execute(
                    canonical_nodes.update()
                    .where(canonical_nodes.c.canonical_key == node.canonical_key)
                    .values(**values, updated_at=_now())
                    .returning(*_NODE_COLS)
                )
            ).first()
            return _row_to_node(row)

    async def bump_version(
        self, canonical_key: str, *, origin: str, embedding: list[float] | None = None
    ) -> Node:
        """Canonicalizer MERGE path for an *unlocked* node: version += 1, re-stamp origin."""
        async with self._sm() as session, session.begin():
            vals: dict = {
                "version": canonical_nodes.c.version + 1,
                "origin": origin,
                "updated_at": _now(),
            }
            if embedding is not None:
                vals["embedding"] = embedding
            row = (
                await session.execute(
                    canonical_nodes.update()
                    .where(canonical_nodes.c.canonical_key == canonical_key)
                    .values(**vals)
                    .returning(*_NODE_COLS)
                )
            ).first()
            if row is None:
                raise NotFoundError(f"node {canonical_key!r} not found")
            return _row_to_node(row)

    async def delete_unlocked_by_source_prefix(self, prefix: str) -> int:
        """Delete unlocked nodes whose source_ref starts with `prefix` (cascades to
        their edges + overlay). Locked/authored nodes are never touched."""
        async with self._sm() as session, session.begin():
            result = await session.execute(
                canonical_nodes.delete().where(
                    canonical_nodes.c.locked.is_(False)
                    & canonical_nodes.c.source_ref.like(f"{prefix}%")
                )
            )
            return result.rowcount

    async def add_edge(
        self,
        src: UUID,
        dst: UUID,
        type: EdgeType,
        origin: str = "authored",
        weight: float = 1.0,
    ) -> Edge:
        """Idempotent on (src, dst, type) — re-adding an edge never duplicates."""
        async with self._sm() as session, session.begin():
            stmt = (
                pg_insert(edges)
                .values(
                    src_node=src, dst_node=dst, type=type, origin=origin, weight=weight
                )
                .on_conflict_do_update(
                    index_elements=["src_node", "dst_node", "type"],
                    set_={"weight": weight},
                )
                .returning(
                    edges.c.id,
                    edges.c.src_node,
                    edges.c.dst_node,
                    edges.c.type,
                    edges.c.weight,
                    edges.c.origin,
                )
            )
            row = (await session.execute(stmt)).first()
            m = row._mapping
            return Edge(
                id=m[edges.c.id],
                src_node=m[edges.c.src_node],
                dst_node=m[edges.c.dst_node],
                type=m[edges.c.type],
                weight=m[edges.c.weight],
                origin=m[edges.c.origin],
            )

    # -- seed inserts (explicit ids, idempotent) ------------------------------

    async def seed_source(self, record: dict) -> bool:
        return await self._insert_ignore(sources, _strip_nulls(record), ["id"])

    async def seed_spine(self, record: dict) -> bool:
        return await self._insert_ignore(spines, _strip_nulls(record), ["id"])

    async def seed_node(self, record: dict, embedding: list[float] | None) -> bool:
        payload = _strip_nulls(record)
        payload.pop("embedding", None)  # seed file ships null; we set the real vector
        if embedding is not None:
            payload["embedding"] = embedding
        return await self._insert_ignore(canonical_nodes, payload, ["id"])

    async def seed_edge(self, record: dict) -> bool:
        return await self._insert_ignore(
            edges, _strip_nulls(record), ["src_node", "dst_node", "type"]
        )

    async def _insert_ignore(
        self, table, values: dict, conflict_cols: list[str]
    ) -> bool:
        async with self._sm() as session, session.begin():
            stmt = (
                pg_insert(table)
                .values(**values)
                .on_conflict_do_nothing(index_elements=conflict_cols)
                .returning(table.c[conflict_cols[0]])
            )
            inserted = (await session.execute(stmt)).first()
            return inserted is not None

    # -- reads ----------------------------------------------------------------

    async def get_node_by_key(self, canonical_key: str) -> Node | None:
        async with self._sm() as session:
            row = (
                await session.execute(
                    select(*_NODE_COLS).where(
                        canonical_nodes.c.canonical_key == canonical_key
                    )
                )
            ).first()
        return _row_to_node(row) if row else None

    async def list_nodes(
        self, kinds: list[str] | None = None, limit: int = 100
    ) -> list[Node]:
        """List nodes, optionally filtered by kind — for facet drill-down / browse."""
        stmt = select(*_NODE_COLS)
        if kinds:
            stmt = stmt.where(canonical_nodes.c.kind.in_(kinds))
        stmt = stmt.order_by(canonical_nodes.c.title).limit(limit)
        async with self._sm() as session:
            rows = (await session.execute(stmt)).all()
        return [_row_to_node(r) for r in rows]

    async def existing_node_ids(self, ids: list[UUID]) -> set[UUID]:
        if not ids:
            return set()
        async with self._sm() as session:
            rows = (
                await session.execute(
                    select(canonical_nodes.c.id).where(canonical_nodes.c.id.in_(ids))
                )
            ).all()
        return {r._mapping[canonical_nodes.c.id] for r in rows}

    async def nearest(
        self, embedding: list[float], *, exclude_key: str | None = None
    ) -> tuple[Node, float] | None:
        """Nearest canonical node by cosine distance, or None if the library is empty.
        Returns (node, cosine_distance) where similarity = 1 - distance."""
        distance = canonical_nodes.c.embedding.cosine_distance(embedding).label(
            "distance"
        )
        stmt = select(*_NODE_COLS, distance).where(
            canonical_nodes.c.embedding.is_not(None)
        )
        if exclude_key is not None:
            stmt = stmt.where(canonical_nodes.c.canonical_key != exclude_key)
        stmt = stmt.order_by(distance).limit(1)
        async with self._sm() as session:
            row = (await session.execute(stmt)).first()
        if row is None:
            return None
        return _row_to_node(row), float(row._mapping["distance"])

    async def get_subgraph(self, node_ids: list[UUID], depth: int = 1) -> Subgraph:
        """Nodes in `node_ids` plus their neighborhood out to `depth` hops, and the
        edges among the collected set."""
        async with self._sm() as session:
            frontier = {UUID(str(n)) for n in node_ids}
            collected: set[UUID] = set(frontier)
            collected_edges: dict[UUID, Edge] = {}
            for _ in range(max(depth, 0)):
                if not frontier:
                    break
                rows = (
                    await session.execute(
                        select(
                            edges.c.id,
                            edges.c.src_node,
                            edges.c.dst_node,
                            edges.c.type,
                            edges.c.weight,
                            edges.c.origin,
                        ).where(
                            edges.c.src_node.in_(frontier)
                            | edges.c.dst_node.in_(frontier)
                        )
                    )
                ).all()
                next_frontier: set[UUID] = set()
                for r in rows:
                    m = r._mapping
                    collected_edges[m[edges.c.id]] = Edge(
                        id=m[edges.c.id],
                        src_node=m[edges.c.src_node],
                        dst_node=m[edges.c.dst_node],
                        type=m[edges.c.type],
                        weight=m[edges.c.weight],
                        origin=m[edges.c.origin],
                    )
                    for nid in (m[edges.c.src_node], m[edges.c.dst_node]):
                        if nid not in collected:
                            next_frontier.add(nid)
                collected |= next_frontier
                frontier = next_frontier

            node_rows = (
                await session.execute(
                    select(*_NODE_COLS).where(canonical_nodes.c.id.in_(collected))
                )
            ).all()
            nodes = [_row_to_node(r) for r in node_rows]
            # only keep edges whose both endpoints are in the returned node set
            ids = {n.id for n in nodes}
            kept = [
                e
                for e in collected_edges.values()
                if e.src_node in ids and e.dst_node in ids
            ]
            if not nodes:
                raise NotFoundError("no nodes found for the given ids")
            return Subgraph(nodes=nodes, edges=kept)

    async def list_spines(self) -> list[SpineSummary]:
        async with self._sm() as session:
            rows = (
                await session.execute(
                    select(
                        spines.c.id,
                        spines.c.title,
                        spines.c.subject,
                        spines.c.description,
                        func.jsonb_array_length(spines.c.node_sequence).label("n"),
                    ).order_by(spines.c.subject, spines.c.title)
                )
            ).all()
        return [
            SpineSummary(
                id=r._mapping[spines.c.id],
                title=r._mapping[spines.c.title],
                subject=r._mapping[spines.c.subject],
                description=r._mapping[spines.c.description],
                node_count=r._mapping["n"] or 0,
            )
            for r in rows
        ]

    async def get_spine(self, spine_id: UUID) -> SpineWithNodes:
        async with self._sm() as session:
            spine = (
                await session.execute(
                    select(
                        spines.c.id,
                        spines.c.title,
                        spines.c.subject,
                        spines.c.node_sequence,
                    ).where(spines.c.id == UUID(str(spine_id)))
                )
            ).first()
            if spine is None:
                raise NotFoundError(f"spine {spine_id} not found")
            seq = [UUID(s) for s in spine._mapping[spines.c.node_sequence]]
            node_rows = (
                await session.execute(
                    select(*_NODE_COLS).where(canonical_nodes.c.id.in_(seq))
                )
            ).all()
            by_id = {
                r._mapping[canonical_nodes.c.id]: _row_to_node(r) for r in node_rows
            }
            ordered = [
                by_id[nid] for nid in seq if nid in by_id
            ]  # preserve spine order
            return SpineWithNodes(
                id=spine._mapping[spines.c.id],
                title=spine._mapping[spines.c.title],
                subject=spine._mapping[spines.c.subject],
                nodes=ordered,
            )


def _strip_nulls(record: dict) -> dict:
    """Drop keys whose value is None so DB server-defaults apply (e.g. ingested_at)."""
    return {k: v for k, v in record.items() if v is not None}


def _now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


# Back-compat alias for deps.py during the stub→real swap.
StubContent = Content

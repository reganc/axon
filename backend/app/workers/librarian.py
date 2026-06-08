"""Librarian — background curator (no learner present).

Phase 2 ships the load-bearing curation: merge near-duplicate nodes the live
generation path created (same idea, two nodes). Authored/locked anchors are never
touched. Edges and overlay state are repointed to the survivor before the
duplicate is dropped, so connectivity and progress are preserved.

Refinement of high-confusion nodes, emergent-spine promotion, and edge-weight
decay are noted here as follow-ups; dedup is the one that keeps the library from
rotting and is what Phase 2 asserts.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .. import db
from ..config import Settings, get_settings

log = logging.getLogger("axon.librarian")

_CAND = "locked = false AND origin IN ('ai_generated','ai_extended') AND embedding IS NOT NULL"

_PAIRS_SQL = text(
    f"""
    WITH cand AS (SELECT id, embedding, version, confidence FROM canonical_nodes WHERE {_CAND})
    SELECT a.id AS a_id, b.id AS b_id,
           a.version AS a_ver, b.version AS b_ver,
           a.confidence AS a_conf, b.confidence AS b_conf
    FROM cand a
    JOIN LATERAL (
        SELECT id, embedding, version, confidence FROM cand c
        WHERE c.id <> a.id ORDER BY a.embedding <=> c.embedding LIMIT 1
    ) b ON TRUE
    WHERE (a.embedding <=> b.embedding) <= :td
    """
)


def _pick_survivor(a: dict, b: dict) -> tuple[str, str]:
    """Survivor = higher version, then higher confidence, then smaller id."""
    a_key = (
        a["ver"],
        a["conf"],
        str(b["id"]),
    )  # smaller id wins -> compare via tie-break below
    b_key = (b["ver"], b["conf"], str(a["id"]))
    if a_key > b_key:
        return str(a["id"]), str(b["id"])
    if b_key > a_key:
        return str(b["id"]), str(a["id"])
    lo, hi = sorted([str(a["id"]), str(b["id"])])
    return lo, hi


async def _merge_pair(session: AsyncSession, survivor: str, dead: str) -> None:
    p = {"s": survivor, "d": dead}
    # repoint edges, skipping rows that would collide on (src,dst,type)
    await session.execute(
        text(
            "UPDATE edges e SET src_node = :s WHERE src_node = :d AND NOT EXISTS ("
            " SELECT 1 FROM edges x WHERE x.src_node = :s AND x.dst_node = e.dst_node"
            " AND x.type = e.type)"
        ),
        p,
    )
    await session.execute(
        text(
            "UPDATE edges e SET dst_node = :s WHERE dst_node = :d AND NOT EXISTS ("
            " SELECT 1 FROM edges x WHERE x.dst_node = :s AND x.src_node = e.src_node"
            " AND x.type = e.type)"
        ),
        p,
    )
    await session.execute(text("DELETE FROM edges WHERE src_node = dst_node"))
    # repoint overlay progress, dropping rows that would collide on the PK
    await session.execute(
        text(
            "UPDATE node_states ns SET node_id = :s WHERE node_id = :d AND NOT EXISTS ("
            " SELECT 1 FROM node_states y WHERE y.checkout_id = ns.checkout_id"
            " AND y.node_id = :s)"
        ),
        p,
    )
    # drop the duplicate (cascades its leftover edges / states), promote survivor
    await session.execute(text("DELETE FROM canonical_nodes WHERE id = :d"), p)
    await session.execute(
        text(
            "UPDATE canonical_nodes SET version = version + 1, origin = 'ai_extended',"
            " updated_at = now() WHERE id = :s"
        ),
        p,
    )


async def run_once(
    sessionmaker: async_sessionmaker[AsyncSession] | None = None,
    settings: Settings | None = None,
) -> dict:
    """Run one curation pass. Returns {'merged': n}."""
    sm = sessionmaker or db.session_factory()
    s = settings or get_settings()
    td = 1.0 - s.librarian_merge_threshold

    async with sm() as session, session.begin():
        rows = (await session.execute(_PAIRS_SQL, {"td": td})).all()
        pairs: dict[frozenset[str], tuple[dict, dict]] = {}
        for r in rows:
            m = r._mapping
            a = {"id": m["a_id"], "ver": m["a_ver"], "conf": m["a_conf"]}
            b = {"id": m["b_id"], "ver": m["b_ver"], "conf": m["b_conf"]}
            pairs.setdefault(frozenset([str(a["id"]), str(b["id"])]), (a, b))

        merged = 0
        retired: set[str] = set()
        for a, b in pairs.values():
            survivor, dead = _pick_survivor(a, b)
            if survivor in retired or dead in retired:
                continue  # chain merges to a later pass — keep one pass simple
            await _merge_pair(session, survivor, dead)
            retired.add(dead)
            merged += 1

    if merged:
        log.info("librarian merged %d near-duplicate node(s)", merged)
    return {"merged": merged}


async def run_forever(interval_sec: float | None = None) -> None:
    """Curation loop: a `run_once` pass every `interval_sec` until cancelled. A
    failing pass is logged and the loop continues — one bad pass must not take the
    worker down."""
    s = get_settings()
    interval = s.librarian_interval_sec if interval_sec is None else interval_sec
    log.info("librarian worker up (interval=%.0fs)", interval)
    try:
        while True:
            try:
                await run_once()
            except Exception:  # noqa: BLE001 - keep curating despite a bad pass
                log.exception("librarian pass failed; continuing")
            await asyncio.sleep(interval)
    finally:
        await db.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(run_forever())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

"""Deep-dive cache: a reopened card should not re-stream the LLM.

A deep-dive explanation is deterministic content for a given (node content,
delivery level): re-generating it on every reopen — across sessions, devices,
and learners — costs seconds of silence and LLM tokens for an answer the
library already produced. The cache stores the flushed narration sentences
plus the material cards' replay data (ids + edges), so a hit narrates
instantly and re-surfaces the material cards from the DB with zero LLM calls.

Keys include a fingerprint of the node's content, so the canonicalizer
augmenting a node naturally invalidates its stale dives. Both backends are
best-effort: any cache failure means a miss, never a broken turn.
"""

from __future__ import annotations

import hashlib
import json
import logging

from ... import bus

log = logging.getLogger("axon.companion.cache")


def dive_key(
    node_id, level: str | None, content: str, band: str = "-", depth: int = 0
) -> str:
    """`axon:dive:{node}:{level}:{mastery-band}:d{depth}:{content-fingerprint}`
    — the coarse mastery band keeps personalized dives shareable across
    learners in the same band instead of fragmenting the cache per learner.
    `depth` keys each rung of the go-deeper ladder separately, so asking to
    dig deeper generates a genuinely deeper pass instead of replaying the
    first one."""
    digest = hashlib.sha1(content.encode("utf-8")).hexdigest()[:12]
    return f"axon:dive:{node_id}:{level or 'default'}:{band}:d{depth}:{digest}"


class RedisDiveCache:
    """Production cache on the stack's Redis (shared with the event bus)."""

    def __init__(self, ttl_s: int) -> None:
        self._ttl_s = ttl_s

    async def get(self, key: str) -> dict | None:
        if self._ttl_s <= 0:
            return None
        try:
            raw = await bus.client().get(key)
            return json.loads(raw) if raw else None
        except Exception as exc:  # noqa: BLE001 - a cache failure is a miss
            log.debug("dive cache get skipped (%s)", exc)
            return None

    async def put(self, key: str, value: dict) -> None:
        if self._ttl_s <= 0:
            return
        try:
            await bus.client().set(key, json.dumps(value), ex=self._ttl_s)
        except Exception as exc:  # noqa: BLE001
            log.debug("dive cache put skipped (%s)", exc)


class MemoryDiveCache:
    """Dict-backed cache for tests and cacheless dev — no TTL, no Redis."""

    def __init__(self) -> None:
        self.store: dict[str, dict] = {}

    async def get(self, key: str) -> dict | None:
        return self.store.get(key)

    async def put(self, key: str, value: dict) -> None:
        self.store[key] = value

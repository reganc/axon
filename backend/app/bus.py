"""bus.py — Redis pub/sub for the companion event stream.

Each event the Tutor emits is also published to `axon:checkout:{id}` so a second
device can subscribe and mirror the session. Publishing is best-effort: if Redis
is down the live WebSocket still works, the fan-out is just skipped.
"""

from __future__ import annotations

import json
import logging

import redis.asyncio as redis

from .config import get_settings

log = logging.getLogger("axon.bus")

_client: redis.Redis | None = None


def client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(get_settings().redis_url, decode_responses=True)
    return _client


def channel(checkout_id) -> str:
    return f"axon:checkout:{checkout_id}"


async def publish(checkout_id, event: dict) -> None:
    try:
        await client().publish(channel(checkout_id), json.dumps(event))
    except Exception as exc:  # noqa: BLE001 - fan-out is optional, never fail a turn
        log.debug("redis publish skipped (%s)", exc)


async def close() -> None:
    global _client
    if _client is not None:
        try:
            await _client.aclose()
        finally:
            _client = None

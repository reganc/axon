"""embeddings.py — fallback + circuit-breaker behaviour (no DB, no network).

These exercise the fast-degradation path: a short per-call timeout makes a
single embed fall back quickly, and the breaker then skips the wedged primary
entirely so a whole seed/session doesn't pay the timeout on every node.
"""

from __future__ import annotations

import httpx

from app.config import Settings
from app.embeddings import (
    DeterministicEmbedder,
    FallbackEmbedder,
    OllamaEmbedder,
    build_embedder,
)


class _Clock:
    """A hand-cranked monotonic clock so cooldowns are deterministic."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


class _Scripted:
    """Embedder that succeeds/fails per a boolean script, counting calls."""

    def __init__(self, script: list[bool]) -> None:
        self.script = script
        self.calls = 0

    async def embed(self, text: str) -> list[float]:
        ok = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        if not ok:
            raise httpx.ConnectError("primary down")
        return [1.0] + [0.0] * 7


def _fb(primary, **kw) -> FallbackEmbedder:
    return FallbackEmbedder(primary, DeterministicEmbedder(dim=8), **kw)


async def test_falls_back_to_deterministic_on_primary_failure():
    emb = _fb(_Scripted([False]))
    vec = await emb.embed("x")
    assert len(vec) == 8
    assert abs(sum(v * v for v in vec) - 1.0) < 1e-9  # deterministic unit vector


async def test_breaker_trips_after_threshold_and_skips_primary():
    primary = _Scripted([False])  # always fails
    emb = _fb(primary, breaker_threshold=3, breaker_cooldown=60.0, clock=_Clock())

    for _ in range(3):
        await emb.embed("warm")
    assert primary.calls == 3  # breaker now open

    for _ in range(5):
        await emb.embed("cold")  # served straight from the fallback
    assert primary.calls == 3  # primary never touched while tripped


async def test_breaker_half_opens_after_cooldown():
    primary = _Scripted([False])
    clock = _Clock()
    emb = _fb(primary, breaker_threshold=2, breaker_cooldown=30.0, clock=clock)

    await emb.embed("a")
    await emb.embed("b")  # 2 failures -> tripped at t=0 until t=30
    await emb.embed("c")  # still open
    assert primary.calls == 2

    clock.t = 31.0  # cooldown elapsed -> half-open, probe the primary again
    await emb.embed("d")
    assert primary.calls == 3


async def test_breaker_resets_on_intervening_success():
    # fail, fail, OK, fail, fail with threshold 3: the success resets the run,
    # so the breaker never trips and the primary is tried every time.
    primary = _Scripted([False, False, True, False, False])
    emb = _fb(primary, breaker_threshold=3, breaker_cooldown=60.0, clock=_Clock())

    for _ in range(5):
        await emb.embed("t")
    assert primary.calls == 5
    assert emb._open_until == 0.0  # never tripped


async def test_breaker_disabled_when_threshold_non_positive():
    primary = _Scripted([False])
    emb = _fb(primary, breaker_threshold=0, breaker_cooldown=60.0, clock=_Clock())
    for _ in range(5):
        await emb.embed("t")
    assert primary.calls == 5  # always retried; breaker off


def test_build_embedder_wires_timeout_and_breaker_from_config():
    s = Settings(
        embed_backend="ollama",
        ollama_base_url="http://example:11434",
        embed_timeout=2.5,
        embed_breaker_threshold=4,
        embed_breaker_cooldown=12.0,
    )
    emb = build_embedder(s)
    assert isinstance(emb, FallbackEmbedder)
    assert isinstance(emb.primary, OllamaEmbedder)
    assert emb.primary.timeout == 2.5
    assert emb.breaker_threshold == 4
    assert emb.breaker_cooldown == 12.0


def test_build_embedder_deterministic_backend_skips_ollama():
    s = Settings(embed_backend="deterministic")
    assert isinstance(build_embedder(s), DeterministicEmbedder)

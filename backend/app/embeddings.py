"""embeddings.py — shared embedding infrastructure for Phase 1.

Canonicalization, related-edge inference, and semantic search all need a vector
for a chunk of text. Phase 1 owns a thin embedder here; Phase 2 routes the same
concern through `LLMPort.embed` (the companion's LLM gateway). Two backends:

- `OllamaEmbedder` — the real one: nomic-embed-text on the local Ollama host,
  768-dim, what the spec calls for and what makes semantic search meaningful.
- `DeterministicEmbedder` — offline fallback: a stable hash-seeded unit vector so
  the app (and unit tests) work with no Ollama. NOT semantically meaningful;
  exact-key/merge logic still works, but ranking quality does not.

The factory prefers Ollama and falls back to deterministic, so nothing hard-fails
when the model host is down.
"""

from __future__ import annotations

import hashlib
import logging
import math
import random
from typing import Protocol, runtime_checkable

import httpx

from .config import Settings, get_settings

log = logging.getLogger("axon.embeddings")


@runtime_checkable
class Embedder(Protocol):
    async def embed(self, text: str) -> list[float]: ...


def _unit(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0:
        return vec
    return [x / norm for x in vec]


class DeterministicEmbedder:
    """Hash-seeded pseudo-embedding. Same text → same vector, always."""

    def __init__(self, dim: int = 768) -> None:
        self.dim = dim

    async def embed(self, text: str) -> list[float]:
        seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")
        rng = random.Random(seed)
        return _unit([rng.gauss(0.0, 1.0) for _ in range(self.dim)])


class OllamaEmbedder:
    """nomic-embed-text via the Ollama HTTP API."""

    def __init__(
        self, base_url: str, model: str, dim: int = 768, timeout: float = 30.0
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dim = dim
        self.timeout = timeout

    async def embed(self, text: str) -> list[float]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/api/embeddings",
                json={"model": self.model, "prompt": text},
            )
            resp.raise_for_status()
            vec = resp.json()["embedding"]
        if len(vec) != self.dim:
            raise ValueError(
                f"embedding dim mismatch: model returned {len(vec)}, expected {self.dim}"
            )
        return _unit(vec)


class FallbackEmbedder:
    """Try the primary embedder; on transport failure fall back to deterministic.

    The fallback is logged loudly — degraded ranking is a real (if non-fatal)
    condition, not something to swallow silently.
    """

    def __init__(self, primary: Embedder, fallback: Embedder) -> None:
        self.primary = primary
        self.fallback = fallback

    async def embed(self, text: str) -> list[float]:
        try:
            return await self.primary.embed(text)
        except (httpx.HTTPError, OSError, ValueError) as exc:
            log.warning(
                "primary embedder failed (%s); using deterministic fallback", exc
            )
            return await self.fallback.embed(text)


def build_embedder(settings: Settings | None = None) -> Embedder:
    s = settings or get_settings()
    deterministic = DeterministicEmbedder(dim=s.embed_dim)
    if s.embed_backend == "deterministic" or not s.ollama_base_url:
        return deterministic
    ollama = OllamaEmbedder(
        base_url=s.ollama_base_url, model=s.ollama_embed_model, dim=s.embed_dim
    )
    return FallbackEmbedder(primary=ollama, fallback=deterministic)

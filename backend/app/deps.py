"""deps.py — the wiring. Provider functions return the concrete implementation
behind each port. Phase 1 wires identity/content/library/ingestion to real seams;
learning/companion/llm remain stubs until Phase 2. Routers depend only on these
providers + the port types, so swapping a stub for a real seam never touches a
router.
"""

from __future__ import annotations

from functools import lru_cache

from . import db
from .config import get_settings
from .embeddings import Embedder, build_embedder
from .seams.companion import StubCompanion, StubLLM
from .seams.content import Content
from .seams.identity import JwtAuth
from .seams.ingestion import Ingestion
from .seams.learning import StubLearning
from .seams.library import Library


@lru_cache
def auth() -> JwtAuth:
    return JwtAuth(get_settings())


@lru_cache
def embedder() -> Embedder:
    return build_embedder(get_settings())


@lru_cache
def content() -> Content:
    return Content(db.session_factory())


@lru_cache
def library() -> Library:
    return Library(db.session_factory(), embedder())


@lru_cache
def ingestion() -> Ingestion:
    return Ingestion(content=content(), embedder=embedder(), settings=get_settings())


# -- Phase 2 stubs (unchanged) --------------------------------------------------


@lru_cache
def llm() -> StubLLM:
    return StubLLM()


@lru_cache
def learning() -> StubLearning:
    return StubLearning()


@lru_cache
def companion() -> StubCompanion:
    return StubCompanion(llm=llm(), library=library())

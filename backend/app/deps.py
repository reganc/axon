"""deps.py — the wiring. Provider functions return the concrete implementation
behind each port. Phase 0 returns stubs; later phases swap these for real seams
without touching the routers (which depend only on the provider + the port type).
"""
from __future__ import annotations

from functools import lru_cache

from .seams.companion import StubCompanion, StubLLM
from .seams.content import StubContent
from .seams.identity import StubAuth
from .seams.ingestion import StubIngestion
from .seams.learning import StubLearning
from .seams.library import StubLibrary


@lru_cache
def auth() -> StubAuth:
    return StubAuth()


@lru_cache
def content() -> StubContent:
    return StubContent()


@lru_cache
def library() -> StubLibrary:
    return StubLibrary()


@lru_cache
def learning() -> StubLearning:
    return StubLearning()


@lru_cache
def llm() -> StubLLM:
    return StubLLM()


@lru_cache
def companion() -> StubCompanion:
    return StubCompanion(llm=llm(), library=library())


@lru_cache
def ingestion() -> StubIngestion:
    return StubIngestion(llm=llm(), content=content())

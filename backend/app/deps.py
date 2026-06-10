"""deps.py — the wiring. Provider functions return the concrete implementation
behind each port. Phases 1–2 wire all six seams to real implementations; routers
depend only on these providers + the port types, so swapping an implementation
never touches a router.
"""

from __future__ import annotations

from functools import lru_cache

from . import db
from .config import get_settings
from .cost import CostController, DbBudgetGate, DbUsageMeter, RoutingPolicy
from .embeddings import Embedder, build_embedder
from .seams.companion import Companion
from .seams.companion.cache import RedisDiveCache
from .seams.companion.llm import LLMGateway
from .seams.content import Content
from .seams.identity import JwtAuth
from .seams.ingestion import Ingestion
from .seams.learning import Learning
from .seams.library import Library
from .voice import SttEngine, TtsEngine


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
    return Ingestion(
        content=content(), embedder=embedder(), settings=get_settings(), llm=llm()
    )


@lru_cache
def cost_controller() -> CostController:
    sm = db.session_factory()
    s = get_settings()
    return CostController(RoutingPolicy(s), DbUsageMeter(sm), DbBudgetGate(sm, s))


@lru_cache
def llm() -> LLMGateway:
    return LLMGateway(get_settings(), embedder(), controller=cost_controller())


@lru_cache
def learning() -> Learning:
    return Learning(db.session_factory())


@lru_cache
def companion() -> Companion:
    return Companion(
        llm=llm(),
        library=library(),
        ingestion=ingestion(),
        content=content(),
        learning=learning(),
        settings=get_settings(),
        dive_cache=RedisDiveCache(get_settings().companion_dive_cache_ttl_s),
    )


@lru_cache
def tts_engine() -> TtsEngine:
    return TtsEngine(get_settings())


@lru_cache
def stt_engine() -> SttEngine:
    return SttEngine(get_settings())

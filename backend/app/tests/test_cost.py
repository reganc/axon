"""Cost control (specs/06) — routing, cost estimation, metering, budget breaker."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import Settings
from app.cost import (
    CostController,
    DbBudgetGate,
    DbUsageMeter,
    Routed,
    RoutingPolicy,
    estimate_cost_usd,
)
from app.embeddings import DeterministicEmbedder
from app.ports import Msg
from app.seams.companion.llm import FakeLLM, LLMGateway

from .conftest import DB_URL, requires_db, scalar


def _sm():
    return async_sessionmaker(
        create_async_engine(DB_URL, poolclass=NullPool), expire_on_commit=False
    )


# -- unit: routing + cost (no DB) ---------------------------------------------


def test_routing_local_tasks_never_hit_cloud():
    r = RoutingPolicy(Settings())
    for task in ("narration", "ask", "recall", "embed"):
        routed = r.route(task)
        assert routed.tier == "local" and routed.model is None


def test_routing_cloud_tasks_pick_models():
    r = RoutingPolicy(Settings())
    assert r.route("plan").tier == "cloud" and "sonnet" in r.route("plan").model
    assert r.route("ground").batch is True  # latency-tolerant -> batch
    assert "haiku" in r.route("extract").model  # cheap cloud
    assert r.route("classify").batch is False


def test_draft_escalates_only_below_floor():
    r = RoutingPolicy(Settings(escalate_floor=0.6))
    assert r.route("draft", confidence=0.9).tier == "local"
    assert r.route("draft", confidence=0.3).tier == "cloud"


def test_cost_estimation():
    assert estimate_cost_usd(None, input_tokens=1000) == 0.0  # local is free
    full = estimate_cost_usd("claude-sonnet-4-6", input_tokens=1000, output_tokens=1000)
    assert full == pytest.approx((1000 * 3 + 1000 * 15) / 1_000_000)
    cached = estimate_cost_usd(
        "claude-sonnet-4-6",
        input_tokens=1000,
        cached_input_tokens=1000,
        output_tokens=0,
    )
    fresh = estimate_cost_usd("claude-sonnet-4-6", input_tokens=1000, output_tokens=0)
    assert cached < fresh  # cache reads are ~10% of fresh input


# -- DB: metering + budget circuit breaker ------------------------------------


@requires_db
async def test_meter_records_cloud_with_cost_and_local_free():
    meter = DbUsageMeter(_sm())
    uid = uuid4()
    cloud = await meter.record(
        task="plan",
        role="companion",
        routed=Routed(tier="cloud", model="claude-sonnet-4-6"),
        input_tokens=1000,
        cached_input_tokens=0,
        output_tokens=200,
        checkout_id=None,
        user_id=uid,
    )
    local = await meter.record(
        task="narration",
        role="companion",
        routed=Routed(tier="local", model=None),
        input_tokens=500,
        cached_input_tokens=0,
        output_tokens=100,
        checkout_id=None,
        user_id=uid,
    )
    assert cloud > 0 and local == 0.0
    assert (
        await scalar("SELECT count(*) FROM usage_events WHERE user_id = :u", u=uid) == 2
    )
    # narration (and embeddings) never recorded as a cloud call
    assert (
        await scalar(
            "SELECT count(*) FROM usage_events WHERE user_id = :u AND task = 'narration' AND tier = 'cloud'",
            u=uid,
        )
        == 0
    )


@requires_db
async def test_budget_breaker_trips_for_user_over_soft_limit():
    sm = _sm()
    # tiny per-user budget; leave global/session loose so other tests' usage
    # doesn't trip this assertion
    budget_cfg = Settings(
        budget_user_daily_usd=0.001,
        budget_global_daily_usd=1_000_000,
        budget_session_usd=1_000_000,
        budget_soft_fraction=0.5,
    )
    meter, gate = DbUsageMeter(sm), DbBudgetGate(sm, budget_cfg)
    uid = uuid4()
    assert await gate.over_soft_limit(user_id=uid) is False

    await meter.record(
        task="plan",
        role="companion",
        routed=Routed(tier="cloud", model="claude-sonnet-4-6"),
        input_tokens=5000,
        cached_input_tokens=0,
        output_tokens=2000,
        checkout_id=None,
        user_id=uid,
    )
    assert await gate.over_soft_limit(user_id=uid) is True


@requires_db
async def test_controller_degrades_cloud_to_local_when_over_budget():
    sm = _sm()
    cfg = Settings(
        budget_user_daily_usd=0.001,
        budget_global_daily_usd=1_000_000,
        budget_session_usd=1_000_000,
        budget_soft_fraction=0.5,
    )
    meter = DbUsageMeter(sm)
    controller = CostController(RoutingPolicy(cfg), meter, DbBudgetGate(sm, cfg))
    uid = uuid4()

    # under budget: planning is cloud
    assert (await controller.route("plan", user_id=uid)).tier == "cloud"

    # blow the budget
    await meter.record(
        task="plan",
        role="companion",
        routed=Routed(tier="cloud", model="claude-sonnet-4-6"),
        input_tokens=5000,
        cached_input_tokens=0,
        output_tokens=2000,
        checkout_id=None,
        user_id=uid,
    )

    # over budget: planning degrades to local; narration was always local
    assert (await controller.route("plan", user_id=uid)).tier == "local"
    assert (await controller.route("narration", user_id=uid)).tier == "local"


@requires_db
async def test_gateway_meters_a_tagged_cloud_call():
    sm = _sm()
    controller = CostController(
        RoutingPolicy(Settings()), DbUsageMeter(sm), DbBudgetGate(sm, Settings())
    )
    gw = LLMGateway(
        Settings(ollama_base_url="", anthropic_api_key="", anthropic_model=""),
        DeterministicEmbedder(768),
        fake=FakeLLM(lambda _m: "OK"),
        controller=controller,
    )
    gw._fast = None
    gw._anthropic = None
    cid, uid = uuid4(), uuid4()

    out = await gw.complete(
        [Msg(role="user", content="x" * 80)],
        "reason",
        task="plan",
        checkout_id=cid,
        user_id=uid,
    )
    assert out == "OK"
    assert (
        await scalar("SELECT count(*) FROM usage_events WHERE checkout_id = :c", c=cid)
        == 1
    )
    row = await scalar("SELECT tier FROM usage_events WHERE checkout_id = :c", c=cid)
    assert row == "cloud"  # routing decided cloud; the meter records the decision

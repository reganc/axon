"""cost.py — LLM cost control (specs/06).

Makes runaway spend structurally impossible, not merely unlikely:

- **Routing** (`RoutingPolicy`): each task is local (Ollama, $0) or cloud, and
  cloud tasks pick a model + whether they batch. Narration/embeddings/recall are
  always local; planning/grounding are cloud; extraction/classification are cheap
  cloud. Local drafts escalate to cloud only below a confidence floor.
- **Metering** (`UsageMeter`): every cloud call is recorded — task, role, tier,
  model, fresh vs cached tokens, estimated cost — to the `usage_events` ledger.
- **Budget + circuit breaker** (`BudgetGate`): per-session / per-user-day /
  global-day ceilings. Over the soft threshold, `CostController` degrades cloud
  work to local so narration and drafts keep working while planning/grounding
  drop to the local model (a full impl queues them for the nightly batch).

The library is a cache: generation cost front-loads and decays, so the policy
maximizes reuse, never pre-generates, and keeps canonicalization LLM-free outside
its gray band.
"""

from __future__ import annotations

from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .config import Settings, get_settings
from .tables import usage_events

TaskKind = Literal[
    "narration",
    "ask",
    "discuss",  # node-scoped follow-up chat
    "media",  # find/diagram visual aids (needs the gateway's web search)
    "recall",
    "embed",
    "draft",
    "hook",  # local
    "extract",
    "classify",
    "curate",  # cheap cloud (batchable)
    "plan",
    "merge_judgment",
    "ground",  # reasoning cloud
]

Tier = Literal["local", "cloud"]

# `media` is local-only on purpose: it relies on the gateway's injected web
# search, which the cloud (Anthropic) tier doesn't have — so it never joins
# _FAST_CHAT_TASKS (which would redirect it to the cloud when fast_tier=cloud).
_LOCAL_TASKS = {
    "narration",
    "ask",
    "discuss",
    "media",
    "recall",
    "embed",
    "draft",
    "hook",
}
_ESCALATABLE = {"draft", "hook"}  # a weak local draft may earn a cloud pass
# Fast-tier *chat* tasks: redirected to the cheap cloud model when
# settings.fast_tier == "cloud". Excludes embed (always Ollama) and recall
# (scheduling, not an LLM chat call).
_FAST_CHAT_TASKS = {"narration", "ask", "discuss", "draft", "hook"}
# cloud task -> (settings field holding the model id, batchable). Each task names
# its own model so cheap/structuring work (extract/classify/curate/plan) and
# research grounding run on Haiku, while merge_judgment — which permanently
# shapes the canonical graph — stays on the strong reasoning model.
_CLOUD_TASKS: dict[str, tuple[str, bool]] = {
    "extract": ("model_cheap", True),
    "classify": ("model_cheap", False),
    "curate": ("model_cheap", True),
    "plan": ("model_cheap", False),
    "ground": ("model_ground", True),
    "merge_judgment": ("model_reason", False),
}

# Representative $/Mtok (input, output) — mid-2026 order of magnitude; the policy
# is rate-independent, only the constants move. Cached input ≈ 10% of input.
_RATES: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-6": (5.0, 25.0),
}
_DEFAULT_RATE = (3.0, 15.0)
_CACHED_INPUT_FRACTION = 0.1


class Routed(BaseModel):
    tier: Tier
    model: str | None = None  # cloud model id, or None for local
    batch: bool = False


def estimate_cost_usd(
    model: str | None,
    *,
    input_tokens: int,
    cached_input_tokens: int = 0,
    output_tokens: int = 0,
) -> float:
    """Estimated USD for a cloud call. Local calls (model=None) are $0."""
    if model is None:
        return 0.0
    rate_in, rate_out = _RATES.get(model, _DEFAULT_RATE)
    fresh = max(0, input_tokens - cached_input_tokens)
    dollars = (
        fresh * rate_in
        + cached_input_tokens * rate_in * _CACHED_INPUT_FRACTION
        + output_tokens * rate_out
    ) / 1_000_000
    return round(dollars, 8)


def estimate_tokens(text_value: str) -> int:
    """Cheap token estimate (~4 chars/token) for metering without the live API."""
    return max(1, len(text_value) // 4)


class RoutingPolicy:
    """Pure task -> Routed mapping. No I/O."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._s = settings or get_settings()

    def route(self, task: TaskKind, *, confidence: float | None = None) -> Routed:
        if task in _LOCAL_TASKS:
            if (
                task in _ESCALATABLE
                and confidence is not None
                and confidence < self._s.escalate_floor
            ):
                return Routed(tier="cloud", model=self._s.model_reason, batch=False)
            # Opt-in: run the fast tier on the cheap cloud model instead of the
            # slow local 14B. The budget breaker still degrades this to local.
            if self._s.fast_tier == "cloud" and task in _FAST_CHAT_TASKS:
                return Routed(tier="cloud", model=self._s.model_cheap, batch=False)
            return Routed(tier="local", model=None, batch=False)
        model_field, batchable = _CLOUD_TASKS[task]
        model = getattr(self._s, model_field)
        return Routed(
            tier="cloud", model=model, batch=batchable and self._s.batch_enabled
        )


# ---------------------------------------------------------------------------
# Metering + budget (DB-backed)
# ---------------------------------------------------------------------------
class UsageMeter(Protocol):
    async def record(
        self,
        *,
        task: str,
        role: str,
        routed: Routed,
        input_tokens: int,
        cached_input_tokens: int,
        output_tokens: int,
        checkout_id: UUID | None,
        user_id: UUID | None,
    ) -> float: ...


class BudgetGate(Protocol):
    async def spent(
        self,
        window: Literal["session", "user_day", "global_day"],
        *,
        user_id: UUID | None,
        checkout_id: UUID | None,
    ) -> float: ...
    async def over_soft_limit(
        self, *, user_id: UUID | None, checkout_id: UUID | None
    ) -> bool: ...


class DbUsageMeter:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sm = sessionmaker

    async def record(
        self,
        *,
        task: str,
        role: str,
        routed: Routed,
        input_tokens: int,
        cached_input_tokens: int,
        output_tokens: int,
        checkout_id: UUID | None = None,
        user_id: UUID | None = None,
    ) -> float:
        cost = estimate_cost_usd(
            routed.model,
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=output_tokens,
        )
        async with self._sm() as session, session.begin():
            await session.execute(
                usage_events.insert().values(
                    task=task,
                    role=role,
                    tier=routed.tier,
                    model=routed.model,
                    input_tokens=input_tokens,
                    cached_input_tokens=cached_input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=cost,
                    checkout_id=checkout_id,
                    user_id=user_id,
                )
            )
        return cost


class DbBudgetGate:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        settings: Settings | None = None,
    ) -> None:
        self._sm = sessionmaker
        self._s = settings or get_settings()

    async def spent(
        self,
        window: Literal["session", "user_day", "global_day"],
        *,
        user_id: UUID | None = None,
        checkout_id: UUID | None = None,
    ) -> float:
        stmt = select(func.coalesce(func.sum(usage_events.c.cost_usd), 0.0))
        if window == "session":
            stmt = stmt.where(usage_events.c.checkout_id == checkout_id)
        elif window == "user_day":
            stmt = stmt.where(usage_events.c.user_id == user_id).where(
                usage_events.c.ts >= func.date_trunc("day", func.now())
            )
        else:  # global_day
            stmt = stmt.where(usage_events.c.ts >= func.date_trunc("day", func.now()))
        async with self._sm() as session:
            return float((await session.execute(stmt)).scalar() or 0.0)

    async def over_soft_limit(
        self, *, user_id: UUID | None = None, checkout_id: UUID | None = None
    ) -> bool:
        """True once any window crosses its soft fraction — the circuit-breaker trip."""
        frac = self._s.budget_soft_fraction
        checks = [
            (await self.spent("global_day"), self._s.budget_global_daily_usd),
        ]
        if user_id is not None:
            checks.append(
                (
                    await self.spent("user_day", user_id=user_id),
                    self._s.budget_user_daily_usd,
                )
            )
        if checkout_id is not None:
            checks.append(
                (
                    await self.spent("session", checkout_id=checkout_id),
                    self._s.budget_session_usd,
                )
            )
        return any(spent >= limit * frac for spent, limit in checks)


class CostController:
    """Ties routing + budget: route a task, degrading cloud -> local when over the
    soft budget (the circuit breaker). Records usage via the meter."""

    def __init__(
        self,
        routing: RoutingPolicy,
        meter: UsageMeter,
        budget: BudgetGate,
    ) -> None:
        self._routing = routing
        self._meter = meter
        self._budget = budget

    async def route(
        self,
        task: TaskKind,
        *,
        confidence: float | None = None,
        user_id: UUID | None = None,
        checkout_id: UUID | None = None,
    ) -> Routed:
        routed = self._routing.route(task, confidence=confidence)
        if routed.tier == "cloud" and await self._budget.over_soft_limit(
            user_id=user_id, checkout_id=checkout_id
        ):
            # degrade to local — narration/drafts always worked; planning/grounding
            # drop to the local model (a full impl queues them for the nightly batch)
            return Routed(tier="local", model=None, batch=False)
        return routed

    async def record(self, **kwargs) -> float:
        return await self._meter.record(**kwargs)

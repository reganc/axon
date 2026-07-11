"""LLM gateway + agent JSON parsing — unit tests (no DB, no live model)."""

from __future__ import annotations

from app.config import Settings
from app.embeddings import DeterministicEmbedder
from app.ports import Msg
from app.seams.companion.agents import parse_json
from app.seams.companion.llm import FakeLLM, LLMGateway, _sse_delta


def _offline_settings() -> Settings:
    # Clear every chat backend so the gateway must fall back to the FakeLLM —
    # llm_base_url drives the fast tier (ollama_base_url is embeddings only).
    return Settings(
        llm_base_url="",
        ollama_base_url="",
        anthropic_api_key="",
        anthropic_model="",
    )


async def test_fake_complete_and_stream():
    fake = FakeLLM(lambda _msgs: "hello there")
    assert await fake.complete([]) == "hello there"
    chunks = [c async for c in fake.stream([])]
    assert "".join(chunks).strip() == "hello there"


async def test_gateway_falls_back_to_fake_without_backends():
    gw = LLMGateway(
        _offline_settings(),
        DeterministicEmbedder(768),
        fake=FakeLLM(lambda _m: "FAKE"),
    )
    msgs = [Msg(role="user", content="x")]
    assert await gw.complete(msgs, "fast") == "FAKE"
    assert await gw.complete(msgs, "reason") == "FAKE"


async def test_gateway_embed_uses_embedder():
    gw = LLMGateway(_offline_settings(), DeterministicEmbedder(768))
    vec = await gw.embed("abc")
    assert len(vec) == 768


class _CloudStub:
    """Duck-typed AnthropicChat: records the model each stream was asked for."""

    def __init__(self) -> None:
        self.models: list[str | None] = []

    async def stream(self, msgs, *, model=None, raw=False):
        self.models.append(model)
        yield "deep "
        yield "answer."

    async def complete(self, msgs, *, model=None):
        self.models.append(model)
        return "deep answer."


class _RecordingMeter:
    def __init__(self) -> None:
        self.records: list[dict] = []

    async def record(self, **kw) -> float:
        self.records.append(kw)
        return 0.01


class _OpenBudget:
    async def spent(self, *a, **k) -> float:
        return 0.0

    async def over_soft_limit(self, **k) -> bool:
        return False


class _TrippedBudget(_OpenBudget):
    async def over_soft_limit(self, **k) -> bool:
        return True


async def test_stream_deep_dive_routes_to_reason_model_and_meters():
    """task='deep_dive' streams from the reasoning model (not the cheap tier)
    and the call is metered like any other cloud call."""
    settings = _offline_settings()
    cloud = _CloudStub()
    meter = _RecordingMeter()
    from app.cost import CostController, RoutingPolicy

    gw = LLMGateway(
        settings,
        DeterministicEmbedder(768),
        anthropic_chat=cloud,
        fake=FakeLLM(),
        controller=CostController(RoutingPolicy(settings), meter, _OpenBudget()),
    )
    msgs = [Msg(role="user", content="go deeper")]
    out = "".join([c async for c in gw.stream(msgs, "fast", task="deep_dive")])

    assert out == "deep answer."
    assert cloud.models == [settings.model_reason]
    assert len(meter.records) == 1
    assert meter.records[0]["task"] == "deep_dive"
    assert meter.records[0]["routed"].model == settings.model_reason


async def test_stream_deep_dive_degrades_to_local_when_over_budget():
    """The budget breaker still governs task-routed streams: over the soft
    limit, deep_dive falls back to the fast lane and nothing is metered."""
    settings = _offline_settings()
    cloud = _CloudStub()
    meter = _RecordingMeter()
    from app.cost import CostController, RoutingPolicy

    gw = LLMGateway(
        settings,
        DeterministicEmbedder(768),
        anthropic_chat=cloud,
        fake=FakeLLM(lambda _m: "LOCAL"),
        controller=CostController(RoutingPolicy(settings), meter, _TrippedBudget()),
    )
    msgs = [Msg(role="user", content="go deeper")]
    out = "".join([c async for c in gw.stream(msgs, "fast", task="deep_dive")])

    assert "LOCAL" in out  # no fast gateway configured -> the fake stands in
    assert cloud.models == []  # the cloud model was never touched
    assert meter.records == []  # local work is never metered


def test_sse_delta_skips_non_delta_lines():
    # well-formed content delta
    assert _sse_delta('{"choices":[{"delta":{"content":"hi"}}]}') == "hi"
    # the gateway's interleaved metadata lines must be skipped, not fatal
    assert _sse_delta('{"type":"search_results","results":[]}') is None
    assert _sse_delta('{"usage":{"total_tokens":42}}') is None
    assert _sse_delta('{"choices":[]}') is None
    assert _sse_delta("not json") is None
    assert _sse_delta('{"choices":[{"delta":{}}]}') is None  # role-only opener


def test_parse_json_tolerates_fences_and_prose():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('here you go: {"steps": ["x", "y"]} done') == {
        "steps": ["x", "y"]
    }
    assert parse_json("[1, 2, 3]") == [1, 2, 3]
    assert parse_json("not json at all") == {}

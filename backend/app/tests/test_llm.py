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

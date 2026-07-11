"""LLM gateway (LLMPort) — routes by tier and degrades gracefully.

- tier="fast"   -> the centralized llm-app gateway (OpenAI-compatible chat, model
  alias `default`) — narration, quick adaptations, drafts.
- tier="reason" -> the Anthropic API (planning, grounding); falls back to the fast
  gateway when no Anthropic key is configured (AXON_LLM_REASON_FALLBACK_TO_FAST).
- embed         -> the Phase-1 embedder (the box's Ollama nomic-embed-text, 768-d).

Every chat call falls back to a deterministic `FakeLLM` if the live backend
errors, so a turn never hard-crashes on a flaky model host. Tests inject a
`FakeLLM` with a scripted handler for fully deterministic companion behaviour.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Callable

import httpx

from ...config import Settings, get_settings
from ...cost import CostController, TaskKind, estimate_tokens
from ...embeddings import Embedder, build_embedder
from ...ports import Msg, Tier

log = logging.getLogger("axon.llm")


def _as_dicts(msgs: list[Msg]) -> list[dict]:
    return [{"role": m.role, "content": m.content} for m in msgs]


def _sse_delta(data: str) -> str | None:
    """Parse one SSE `data:` payload into a content delta, or None when the line
    isn't a well-formed delta. The gateway interleaves non-delta lines (RAG/search
    metadata, usage) into the stream; those must be skipped, not fatal."""
    try:
        choices = json.loads(data).get("choices") or []
        return choices[0].get("delta", {}).get("content")
    except (json.JSONDecodeError, AttributeError, IndexError, KeyError):
        return None


class GatewayChat:
    """The fast/local tier: the centralized llm-app gateway, OpenAI-compatible
    (`POST {base}/chat/completions`, Bearer auth, model alias `default`). Every
    app on this host shares it — we never hardcode a concrete local model."""

    def __init__(
        self, base_url: str, api_key: str, model: str, timeout: float = 120.0
    ) -> None:
        self.url = f"{base_url.rstrip('/')}/chat/completions"
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.model = model
        self.timeout = timeout

    async def complete(self, msgs: list[Msg], *, model: str | None = None) -> str:
        # `model` is accepted for a uniform backend interface but ignored: the
        # gateway resolves the shared `default` alias server-side and never
        # exposes per-request model choice (see apps/CLAUDE.md).
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                self.url,
                headers=self.headers,
                json={
                    "model": self.model,
                    "messages": _as_dicts(msgs),
                    "stream": False,
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

    async def stream(
        self, msgs: list[Msg], *, model: str | None = None, raw: bool = False
    ) -> AsyncIterator[str]:
        # raw=True is the gateway's per-request opt-out of web-search/RAG
        # injection: ~13s faster to first token (measured) and no citation
        # markers in the prose. Used by the talk streams, whose content is
        # already grounded; never by agents that *need* the search lane.
        payload: dict = {
            "model": self.model,
            "messages": _as_dicts(msgs),
            "stream": True,
        }
        if raw:
            payload["raw"] = True
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST",
                self.url,
                headers=self.headers,
                json=payload,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[len("data:") :].strip()
                    if data == "[DONE]":
                        break
                    delta = _sse_delta(data)
                    if delta:
                        yield delta


class AnthropicChat:
    def __init__(self, api_key: str, model: str, max_tokens: int = 1024) -> None:
        import anthropic

        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._not_given = anthropic.NOT_GIVEN
        self.model = model
        self.max_tokens = max_tokens

    def _split(self, msgs: list[Msg]):
        system = "\n".join(m.content for m in msgs if m.role == "system")
        rest = [
            {"role": m.role, "content": m.content} for m in msgs if m.role != "system"
        ]
        return (system or self._not_given), rest

    async def complete(self, msgs: list[Msg], *, model: str | None = None) -> str:
        system, rest = self._split(msgs)
        resp = await self._client.messages.create(
            model=model or self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=rest,
        )
        return "".join(b.text for b in resp.content if b.type == "text")

    async def stream(
        self, msgs: list[Msg], *, model: str | None = None, raw: bool = False
    ) -> AsyncIterator[str]:
        # `raw` is a gateway concept; the Anthropic lane has no injection.
        system, rest = self._split(msgs)
        async with self._client.messages.stream(
            model=model or self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=rest,
        ) as stream:
            async for text in stream.text_stream:
                yield text


class FakeLLM:
    """Deterministic backend. `handler(msgs) -> str` lets tests script replies by
    inspecting the prompt (agents tag prompts with `TASK: <name>`)."""

    def __init__(self, handler: Callable[[list[Msg]], str] | None = None) -> None:
        self._handler = handler or (lambda _msgs: "OK")

    async def complete(self, msgs: list[Msg], *, model: str | None = None) -> str:
        return self._handler(msgs)

    async def stream(
        self, msgs: list[Msg], *, model: str | None = None, raw: bool = False
    ) -> AsyncIterator[str]:
        for word in self._handler(msgs).split(" "):
            yield word + " "


class LLMGateway:
    """The LLMPort the companion depends on."""

    def __init__(
        self,
        settings: Settings | None = None,
        embedder: Embedder | None = None,
        *,
        fast: GatewayChat | None = None,
        anthropic_chat: AnthropicChat | None = None,
        fake: FakeLLM | None = None,
        controller: "CostController | None" = None,
        role: str = "companion",
    ) -> None:
        s = settings or get_settings()
        self._s = s
        self._controller = controller
        self._role = role
        self._embedder = embedder or build_embedder(s)
        self._fake = fake or FakeLLM()
        # fast/local tier = the centralized llm-app gateway
        self._fast = fast or (
            GatewayChat(s.llm_base_url, s.llm_api_key, s.llm_model)
            if s.llm_base_url
            else None
        )
        if anthropic_chat is not None:
            self._anthropic = anthropic_chat
        elif s.anthropic_api_key and s.anthropic_model:
            self._anthropic = AnthropicChat(
                s.anthropic_api_key, s.anthropic_model, s.anthropic_max_tokens
            )
        else:
            self._anthropic = None

    @classmethod
    def scripted(
        cls, handler, embedder: Embedder, settings: Settings | None = None
    ) -> "LLMGateway":
        """A gateway whose chat is a scripted FakeLLM (no live model) but whose
        `embed` uses the given real embedder. For deterministic companion tests."""
        gw = cls(settings, embedder, fake=FakeLLM(handler))
        gw._fast = None
        gw._anthropic = None
        return gw

    def _backend(self, tier: Tier):
        if tier == "reason":
            if self._anthropic is not None:
                return self._anthropic
            if not self._s.llm_reason_fallback_to_fast:
                return self._fake
        if self._fast is not None:
            return self._fast
        return self._fake

    async def complete(
        self,
        msgs: list[Msg],
        tier: Tier,
        *,
        task: "TaskKind | None" = None,
        confidence: float | None = None,
        checkout_id=None,
        user_id=None,
    ) -> str:
        # Cost control: when a task is named and a controller is wired, the
        # controller decides local vs cloud (degrading to local when over budget)
        # and every cloud call is metered. Otherwise fall back to the raw tier.
        effective = tier
        routed = None
        if task is not None and self._controller is not None:
            routed = await self._controller.route(
                task, confidence=confidence, user_id=user_id, checkout_id=checkout_id
            )
            effective = "reason" if routed.tier == "cloud" else "fast"

        backend = self._backend(effective)
        # The router picked the model (e.g. Haiku for ground/extract, Sonnet for
        # merge_judgment); honor it on the actual call. None -> the backend's own
        # default (local gateway ignores it; Anthropic uses its configured model).
        model = routed.model if routed is not None else None
        try:
            result = await backend.complete(msgs, model=model)
        except Exception as exc:  # noqa: BLE001 - degrade, never crash a turn
            log.warning(
                "llm complete failed on %s (%s); using fake",
                type(backend).__name__,
                exc,
            )
            result = await self._fake.complete(msgs)

        if routed is not None:
            await self._controller.record(
                task=task,
                role=self._role,
                routed=routed,
                input_tokens=sum(estimate_tokens(m.content) for m in msgs),
                cached_input_tokens=0,
                output_tokens=estimate_tokens(result),
                checkout_id=checkout_id,
                user_id=user_id,
            )
        return result

    async def stream(
        self,
        msgs: list[Msg],
        tier: Tier,
        *,
        raw: bool = False,
        task: "TaskKind | None" = None,
        checkout_id=None,
        user_id=None,
    ) -> AsyncIterator[str]:
        backend = self._backend(tier)
        model: str | None = None
        routed = None
        if task is not None and self._controller is not None:
            # Task-routed stream (e.g. deep_dive -> the reasoning model), budget
            # gated and metered like any other cloud call. When the router
            # degrades to local (over budget) or no cloud backend exists, the
            # stream falls through to the fast lane unmetered.
            routed = await self._controller.route(
                task, user_id=user_id, checkout_id=checkout_id
            )
            if routed.tier == "cloud" and self._anthropic is not None:
                backend, model = self._anthropic, routed.model
            else:
                routed = None
        elif (
            tier == "fast"
            and self._s.fast_tier == "cloud"
            and self._anthropic is not None
        ):
            # No task named: honor fast_tier so narration streams from the cheap
            # cloud model instead of the slow local gateway.
            backend, model = self._anthropic, self._s.model_cheap
        out_chars = 0
        try:
            async for chunk in backend.stream(msgs, model=model, raw=raw):
                out_chars += len(chunk)
                yield chunk
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "llm stream failed on %s (%s); using fake", type(backend).__name__, exc
            )
            async for chunk in self._fake.stream(msgs):
                yield chunk
        if routed is not None:
            await self._controller.record(
                task=task,
                role=self._role,
                routed=routed,
                input_tokens=sum(estimate_tokens(m.content) for m in msgs),
                cached_input_tokens=0,
                output_tokens=max(1, out_chars // 4),
                checkout_id=checkout_id,
                user_id=user_id,
            )

    async def embed(self, text: str) -> list[float]:
        return await self._embedder.embed(text)

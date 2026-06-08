"""Companion agents: Planner, NodeGenerator, Researcher.

Each agent is a thin wrapper over the LLM gateway with a tagged prompt
(`TASK: <name>`) so a scripted FakeLLM can drive deterministic tests. JSON
replies are parsed leniently (code fences / surrounding prose tolerated).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from ...config import Settings, get_settings
from ...jsonutil import parse_json
from ...ports import CandidateNode, LLMPort, Msg, Node

log = logging.getLogger("axon.agents")

__all__ = ["Planner", "NodeGenerator", "Researcher", "Elaborator", "parse_json"]


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


class Planner:
    """subject -> ordered list of concept titles (tier=reason)."""

    def __init__(self, llm: LLMPort, settings: Settings | None = None) -> None:
        self._llm = llm
        self._s = settings or get_settings()

    async def plan(self, subject: str, *, checkout_id=None, user_id=None) -> list[str]:
        n = self._s.companion_max_steps
        msgs = [
            Msg(
                role="system",
                content=(
                    "You are AXON's Planner. Decompose a subject into an ordered "
                    "learning path of atomic concept titles, prerequisites first."
                ),
            ),
            Msg(
                role="user",
                content=(
                    f"TASK: plan\nSubject: {subject}\n"
                    f'Return JSON only: {{"steps": ["Concept title", ...]}} '
                    f"with at most {n} concise titles."
                ),
            ),
        ]
        data = parse_json(
            await self._llm.complete(
                msgs, "reason", task="plan", checkout_id=checkout_id, user_id=user_id
            )
        )
        steps = data.get("steps", []) if isinstance(data, dict) else data
        titles = [str(s).strip() for s in steps if str(s).strip()]
        return titles[:n] or [subject]


class NodeGenerator:
    """concept title -> CandidateNode content (tier=fast)."""

    def __init__(self, llm: LLMPort) -> None:
        self._llm = llm

    async def generate(
        self, title: str, subject: str, *, checkout_id=None, user_id=None
    ) -> CandidateNode:
        msgs = [
            Msg(
                role="system",
                content=(
                    "You are AXON's Tutor generating one knowledge-graph node: a "
                    "curiosity hook, a tight explanation, and recall prompts."
                ),
            ),
            Msg(
                role="user",
                content=(
                    f"TASK: generate_node\nConcept: {title}\nSubject: {subject}\n"
                    'Return JSON only: {"hook": "...", "body": "...", '
                    '"recall_prompts": ["..."]}'
                ),
            ),
        ]
        data = parse_json(
            await self._llm.complete(
                msgs, "fast", task="draft", checkout_id=checkout_id, user_id=user_id
            )
        )
        data = data if isinstance(data, dict) else {}
        rp = data.get("recall_prompts") or []
        return CandidateNode(
            title=title,
            hook=(data.get("hook") or None),
            body=(data.get("body") or None),
            recall_prompts=[str(p) for p in rp][:5],
            origin="ai_generated",
            source_ref=f"companion/{subject}",
        )


class Researcher:
    """Ground a generated candidate: set confidence + source_ref (tier=reason).

    Authored/locked content is never sent here. Conversations are leads, not
    authority — below the confidence floor the node is kept but flagged (its low
    confidence is the flag), never published as settled fact.
    """

    def __init__(self, llm: LLMPort, settings: Settings | None = None) -> None:
        self._llm = llm
        self._s = settings or get_settings()

    async def ground(
        self, candidate: CandidateNode, *, checkout_id=None, user_id=None
    ) -> CandidateNode:
        msgs = [
            Msg(
                role="system",
                content=(
                    "You are AXON's Researcher. Judge how well-grounded a generated "
                    "explanation is and assign a calibrated confidence in [0,1]."
                ),
            ),
            Msg(
                role="user",
                content=(
                    f"TASK: ground\nTitle: {candidate.title}\n"
                    f"Body: {candidate.body}\n"
                    'Return JSON only: {"confidence": 0.0-1.0, "source_ref": "..."}'
                ),
            ),
        ]
        data = parse_json(
            await self._llm.complete(
                msgs, "reason", task="ground", checkout_id=checkout_id, user_id=user_id
            )
        )
        data = data if isinstance(data, dict) else {}
        try:
            confidence = _clamp01(float(data.get("confidence", 0.5)))
        except (TypeError, ValueError):
            confidence = 0.5
        return candidate.model_copy(
            update={
                "confidence": confidence,
                "source_ref": data.get("source_ref") or candidate.source_ref,
            }
        )

    @property
    def floor(self) -> float:
        return self._s.companion_confidence_floor


class Elaborator:
    """Deep-dive on an existing node (tier=fast).

    `explain` streams a flowing, spoken-style explanation of the node itself —
    the experience layer, ephemeral talk. `materials` returns study artifacts
    (a key-points summary, an analogy, follow-up questions) as CandidateNodes
    so the caller can persist them through the canonicalize chokepoint.
    """

    def __init__(self, llm: LLMPort, settings: Settings | None = None) -> None:
        self._llm = llm
        self._s = settings or get_settings()

    def explain(self, node: Node) -> AsyncIterator[str]:
        msgs = [
            Msg(
                role="system",
                content=(
                    "You are AXON's Tutor speaking aloud to one learner. Explain the "
                    "concept conversationally and in depth — intuition first, then a "
                    "concrete example, then why it matters. Flowing spoken prose, no "
                    "markdown, no headings, no lists, no citations."
                ),
            ),
            Msg(
                role="user",
                content=(
                    f"TASK: explain\nConcept: {node.title}\n"
                    f"Existing hook: {node.hook or ''}\n"
                    f"Existing notes: {node.body or ''}\n"
                    "Teach it richly, as if thinking out loud with the learner."
                ),
            ),
        ]
        return self._llm.stream(msgs, "fast")

    async def materials(
        self, node: Node, *, checkout_id=None, user_id=None
    ) -> list[CandidateNode]:
        msgs = [
            Msg(
                role="system",
                content=(
                    "You are AXON's Tutor distilling study materials from a concept "
                    "you just explained. Be concise and faithful to the concept."
                ),
            ),
            Msg(
                role="user",
                content=(
                    f"TASK: materials\nConcept: {node.title}\n"
                    f"Notes: {node.body or node.hook or ''}\n"
                    'Return JSON only: {"summary": "3-5 sentence key-points recap", '
                    '"analogy": "one vivid analogy", '
                    '"questions": ["a follow-up question", "another"]}'
                ),
            ),
        ]
        data = parse_json(
            await self._llm.complete(
                msgs, "fast", task="draft", checkout_id=checkout_id, user_id=user_id
            )
        )
        data = data if isinstance(data, dict) else {}
        src = f"companion/deep-dive/{node.id}"
        out: list[CandidateNode] = []
        summary = (data.get("summary") or "").strip()
        if summary:
            out.append(
                CandidateNode(
                    title=f"Key points: {node.title}",
                    kind="artifact",
                    hook="A quick recap of the essentials.",
                    body=summary,
                    origin="ai_generated",
                    source_ref=src,
                    confidence=node.confidence,
                )
            )
        analogy = (data.get("analogy") or "").strip()
        if analogy:
            out.append(
                CandidateNode(
                    title=f"Analogy: {node.title}",
                    kind="artifact",
                    hook="A way to picture it.",
                    body=analogy,
                    origin="ai_generated",
                    source_ref=src,
                    confidence=node.confidence,
                )
            )
        for q in data.get("questions") or []:
            q = str(q).strip()
            if q:
                out.append(
                    CandidateNode(
                        title=q,
                        kind="question",
                        hook=q,
                        origin="ai_generated",
                        source_ref=src,
                        confidence=0.5,
                    )
                )
        return out

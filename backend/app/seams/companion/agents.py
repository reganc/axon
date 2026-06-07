"""Companion agents: Planner, NodeGenerator, Researcher.

Each agent is a thin wrapper over the LLM gateway with a tagged prompt
(`TASK: <name>`) so a scripted FakeLLM can drive deterministic tests. JSON
replies are parsed leniently (code fences / surrounding prose tolerated).
"""

from __future__ import annotations

import logging

from ...config import Settings, get_settings
from ...jsonutil import parse_json
from ...ports import CandidateNode, LLMPort, Msg

log = logging.getLogger("axon.agents")

__all__ = ["Planner", "NodeGenerator", "Researcher", "parse_json"]


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


class Planner:
    """subject -> ordered list of concept titles (tier=reason)."""

    def __init__(self, llm: LLMPort, settings: Settings | None = None) -> None:
        self._llm = llm
        self._s = settings or get_settings()

    async def plan(self, subject: str) -> list[str]:
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
        data = parse_json(await self._llm.complete(msgs, "reason"))
        steps = data.get("steps", []) if isinstance(data, dict) else data
        titles = [str(s).strip() for s in steps if str(s).strip()]
        return titles[:n] or [subject]


class NodeGenerator:
    """concept title -> CandidateNode content (tier=fast)."""

    def __init__(self, llm: LLMPort) -> None:
        self._llm = llm

    async def generate(self, title: str, subject: str) -> CandidateNode:
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
        data = parse_json(await self._llm.complete(msgs, "fast"))
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

    async def ground(self, candidate: CandidateNode) -> CandidateNode:
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
        data = parse_json(await self._llm.complete(msgs, "reason"))
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

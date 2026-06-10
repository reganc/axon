"""Companion agents: Planner, NodeGenerator, Researcher.

Each agent is a thin wrapper over the LLM gateway with a tagged prompt
(`TASK: <name>`) so a scripted FakeLLM can drive deterministic tests. JSON
replies are parsed leniently (code fences / surrounding prose tolerated).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from ...config import Settings, get_settings
from ...grounding import GROUND_SYSTEM, ground_user_prompt, score_verdicts
from ...jsonutil import parse_json
from ...ports import CandidateNode, LLMPort, Msg, Node
from .levels import level_clause

log = logging.getLogger("axon.agents")

__all__ = [
    "Planner",
    "NodeGenerator",
    "Researcher",
    "Elaborator",
    "Conversationalist",
    "MediaScout",
    "Diagrammer",
    "parse_json",
]


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
    """Ground a generated candidate: set confidence + source_ref (tier=fast).

    Authored/locked content is never sent here. Conversations are leads, not
    authority — below the confidence floor the node is kept but flagged (its low
    confidence is the flag), never published as settled fact.

    Grounding goes through the *fast gateway lane on purpose*: it is the only
    lane with injected live web search, so the model verifies claims against
    actual evidence instead of rating its own output from memory. The model
    returns per-claim verdicts; confidence is computed deterministically by
    `score_verdicts`, never self-reported.
    """

    def __init__(self, llm: LLMPort, settings: Settings | None = None) -> None:
        self._llm = llm
        self._s = settings or get_settings()

    async def ground(
        self, candidate: CandidateNode, *, checkout_id=None, user_id=None
    ) -> CandidateNode:
        msgs = [
            Msg(role="system", content=GROUND_SYSTEM),
            Msg(
                role="user",
                content=ground_user_prompt(candidate.title, candidate.body),
            ),
        ]
        # No task routing: the cost controller would bounce this to the cloud
        # tier, which has no web search. Local lane is also free.
        data = parse_json(
            await self._llm.complete(
                msgs, "fast", checkout_id=checkout_id, user_id=user_id
            )
        )
        data = data if isinstance(data, dict) else {}
        if "claims" in data:
            confidence, sources = score_verdicts(data.get("claims"))
            source_ref = sources[0] if sources else candidate.source_ref
        else:
            # Legacy self-reported shape — tolerated when the model ignores the
            # verdict format, so a malformed reply degrades instead of crashing.
            try:
                confidence = _clamp01(float(data.get("confidence", 0.5)))
            except (TypeError, ValueError):
                confidence = 0.5
            source_ref = data.get("source_ref") or candidate.source_ref
        return candidate.model_copy(
            update={"confidence": confidence, "source_ref": source_ref}
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

    def explain(
        self, node: Node, level: str | None = None, learner_clause: str = ""
    ) -> AsyncIterator[str]:
        msgs = [
            Msg(
                role="system",
                content=(
                    "You are AXON's Tutor speaking aloud to one learner. Explain the "
                    "concept conversationally and in depth — intuition first, then a "
                    "concrete example, then why it matters. Flowing spoken prose, no "
                    "markdown, no headings, no lists, no citations."
                    + level_clause(level)
                    + learner_clause
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


class Conversationalist:
    """Node-scoped, multi-turn discussion (tier=fast).

    `reply` streams a spoken-style answer to a learner's follow-up, given the
    prior turns of the discussion as continuity. `extract_concept` decides whether
    the exchange surfaced a *genuinely new* concept worth its own card — the
    auto-accrete trigger — returning a `CandidateNode` (its title seeds the normal
    reuse-or-generate path) or `None` when the turn was only a clarification.
    """

    def __init__(self, llm: LLMPort, settings: Settings | None = None) -> None:
        self._llm = llm
        self._s = settings or get_settings()

    def reply(
        self,
        node: Node,
        history: list[dict],
        question: str,
        level: str | None = None,
        learner_clause: str = "",
    ) -> AsyncIterator[str]:
        convo = "\n".join(f"{t['role']}: {t['text']}" for t in history) or "(none yet)"
        msgs = [
            Msg(
                role="system",
                content=(
                    "You are AXON's Tutor in an ongoing spoken conversation with one "
                    "learner about a specific concept. Answer their follow-up directly "
                    "and build on what was already said — don't repeat it. Flowing "
                    "spoken prose, no markdown, no headings, no lists, no citations."
                    + level_clause(level)
                    + learner_clause
                ),
            ),
            Msg(
                role="user",
                content=(
                    f"TASK: discuss\nConcept: {node.title}\n"
                    f"Notes: {node.body or node.hook or ''}\n"
                    f"Conversation so far:\n{convo}\n"
                    f"Learner asks: {question}\n"
                    "Answer just this, picking up the thread."
                ),
            ),
        ]
        return self._llm.stream(msgs, "fast")

    async def extract_concept(
        self,
        node: Node,
        question: str,
        answer: str,
        *,
        checkout_id=None,
        user_id=None,
    ) -> CandidateNode | None:
        msgs = [
            Msg(
                role="system",
                content=(
                    "You decide whether a tutoring exchange introduced a NEW, distinct "
                    "concept that deserves its own knowledge-graph card — as opposed to "
                    "merely clarifying or rephrasing the concept already under "
                    "discussion. Be conservative: only a genuinely separate idea counts."
                ),
            ),
            Msg(
                role="user",
                content=(
                    f"TASK: extract_concept\nCurrent concept: {node.title}\n"
                    f"Learner asked: {question}\n"
                    f"Tutor answered: {answer}\n"
                    "Return JSON only. If a genuinely new concept emerged: "
                    '{"new_concept": true, "title": "concise concept title", '
                    '"hook": "one-line curiosity hook", "body": "2-4 sentences"}. '
                    'Otherwise: {"new_concept": false}.'
                ),
            ),
        ]
        data = parse_json(
            await self._llm.complete(
                msgs, "fast", task="discuss", checkout_id=checkout_id, user_id=user_id
            )
        )
        data = data if isinstance(data, dict) else {}
        title = str(data.get("title") or "").strip()
        if not data.get("new_concept") or not title:
            return None
        return CandidateNode(
            title=title,
            kind="concept",
            hook=(data.get("hook") or None),
            body=(data.get("body") or None),
            origin="ai_generated",
            source_ref=f"companion/discuss/{node.id}",
            confidence=0.5,
        )


class MediaScout:
    """Propose real external visual aids for a concept (tier=fast).

    Runs on the fast gateway *specifically* because that lane injects web search
    (SearXNG) — so candidate URLs are drawn from the live web, not invented from
    weights. They are still unverified here; the caller resolves each one through
    `media_validation` before anything reaches the learner.
    """

    def __init__(self, llm: LLMPort, settings: Settings | None = None) -> None:
        self._llm = llm
        self._s = settings or get_settings()

    async def find(self, node: Node, *, checkout_id=None, user_id=None) -> dict:
        msgs = [
            Msg(
                role="system",
                content=(
                    "You are AXON's media scout. Using web search, find the single "
                    "best explainer video, a couple of authoritative reference links, "
                    "and one illustrative image for a concept. Prefer well-known "
                    "sources (Wikipedia, university pages, reputable YouTube channels). "
                    "Return only real URLs you actually found — never invent one."
                ),
            ),
            Msg(
                role="user",
                content=(
                    f"TASK: find_media\nConcept: {node.title}\n"
                    f"Context: {node.hook or node.body or ''}\n"
                    'Return JSON only: {"videos": ["https://youtube..."], '
                    '"links": [{"title": "...", "url": "https://..."}], '
                    '"images": ["https://...png"]}. Omit anything you cannot find.'
                ),
            ),
        ]
        data = parse_json(
            await self._llm.complete(
                msgs, "fast", task="media", checkout_id=checkout_id, user_id=user_id
            )
        )
        if not isinstance(data, dict):
            return {"videos": [], "links": [], "images": []}
        return {
            "videos": [str(u) for u in (data.get("videos") or []) if u][:3],
            "links": [
                {
                    "title": str(x.get("title") or x.get("url") or ""),
                    "url": str(x.get("url") or ""),
                }
                for x in (data.get("links") or [])
                if isinstance(x, dict) and x.get("url")
            ][:5],
            "images": [str(u) for u in (data.get("images") or []) if u][:3],
        }


class Diagrammer:
    """Author a single Mermaid diagram for a concept (tier=fast).

    Returns the raw Mermaid source (no code fences, no prose); the caller gates it
    through `validate_mermaid` so malformed output never reaches the renderer.
    """

    def __init__(self, llm: LLMPort, settings: Settings | None = None) -> None:
        self._llm = llm
        self._s = settings or get_settings()

    async def diagram(self, node: Node, *, checkout_id=None, user_id=None) -> str:
        msgs = [
            Msg(
                role="system",
                content=(
                    "You draw one small Mermaid diagram that captures the structure "
                    "of a concept (a flowchart of its parts/flow, or a relationship "
                    "graph). Output ONLY valid Mermaid source — start with a diagram "
                    "declaration like 'graph TD'. No code fences, no commentary, keep "
                    "it to a handful of nodes."
                ),
            ),
            Msg(
                role="user",
                content=(
                    f"TASK: diagram\nConcept: {node.title}\n"
                    f"Notes: {node.hook or node.body or ''}\n"
                    "Return the Mermaid source only."
                ),
            ),
        ]
        text = await self._llm.complete(
            msgs, "fast", task="media", checkout_id=checkout_id, user_id=user_id
        )
        return _strip_code_fence(text)


def _strip_code_fence(text: str) -> str:
    """Drop a surrounding ```mermaid ... ``` fence if the model added one."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1] if "\n" in t else ""
        if t.endswith("```"):
            t = t[:-3]
    return t.strip()

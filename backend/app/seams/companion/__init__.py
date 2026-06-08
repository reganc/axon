"""companion seam — the Tutor event stream (the "Jarvis" mechanism).

Phase 2. A learner names a subject; the Tutor plans it, walks the path narrating
as it goes, reuses what the library already holds and generates only the gaps,
and every generated node flows through Phase 1's canonicalizer into the library.
One typed stream (`StreamEvent`) is produced; the frontend demuxes it into voice
+ canvas.

Optimistic → canonical reconciliation: a generated node is emitted as
`node.create` with a `temp_id` for instant render, then canonicalized; the
canonical id comes back as `node.update`. Talk is the experience layer — the
Phase-1 loop is still the source of truth.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

from ...config import Settings, get_settings
from ...ports import CandidateNode, InteractionEvent, Node, StreamEvent
from ..ingestion import normalize_key
from .agents import Elaborator, NodeGenerator, Planner, Researcher
from .llm import FakeLLM, GatewayChat, LLMGateway  # noqa: F401  (re-exported)

log = logging.getLogger("axon.companion")

# The fast gateway injects web-search/RAG context and leaves citation markers like
# [W2] / [L1] in prose. Strip them (plus stray markdown emphasis) before narration.
_CITATION = re.compile(r"\[[A-Za-z]?\d+\]")
_EMPHASIS = re.compile(r"[*_]{1,2}")
# A sentence boundary: terminal punctuation followed by whitespace.
_SENTENCE = re.compile(r"(.+?[.!?])(\s+)", re.DOTALL)


def _sanitize(text: str) -> str:
    return _EMPHASIS.sub("", _CITATION.sub("", text))


def _flush_sentences(buf: str) -> tuple[str, list[str]]:
    """Pull complete sentences out of a streaming buffer so narration is emitted
    (and spoken) sentence-by-sentence. Returns (remaining_buffer, sentences)."""
    out: list[str] = []
    last = 0
    for m in _SENTENCE.finditer(buf):
        s = _sanitize(m.group(1)).strip()
        if s:
            out.append(s)
        last = m.end()
    return buf[last:], out


def _ev(type_: str, **data) -> StreamEvent:
    return StreamEvent(type=type_, data=data)


def _node_payload(node: Node) -> dict:
    return {
        "id": str(node.id),
        "canonical_key": node.canonical_key,
        "title": node.title,
        "kind": node.kind,
        "hook": node.hook,
        "body": node.body,
        "origin": node.origin,
        "confidence": node.confidence,
        "locked": node.locked,
    }


def _candidate_payload(c: CandidateNode) -> dict:
    return {
        "title": c.title,
        "kind": c.kind,
        "hook": c.hook,
        "body": c.body,
        "origin": c.origin,
    }


class Companion:
    """CompanionPort. Drives the in-session event stream."""

    def __init__(
        self,
        *,
        llm,
        library,
        ingestion,
        content,
        learning,
        settings: Settings | None = None,
    ) -> None:
        self._s = settings or get_settings()
        self._llm = llm
        self._library = library
        self._ingestion = ingestion
        self._content = content
        self._learning = learning
        self._planner = Planner(llm, self._s)
        self._generator = NodeGenerator(llm)
        self._researcher = Researcher(llm, self._s)
        self._elaborator = Elaborator(llm, self._s)

    # -- main loop ------------------------------------------------------------

    async def run_turn(
        self, checkout_id: UUID, message: str, inbox: asyncio.Queue | None = None
    ) -> AsyncIterator[StreamEvent]:
        cid = UUID(str(checkout_id))
        owner = await self._library.checkout_owner(cid)
        yield _ev("status", phase="planning", detail="checking the library…")
        plan = await self._planner.plan(message, checkout_id=cid, user_id=owner)

        prev_id: UUID | None = None
        produced = 0
        for title in plan:
            barge = _drain(inbox)
            if barge and barge.get("type") == "interrupt":
                title = (barge.get("text") or title).strip()
                yield _ev("say", text=f"Sure — let's switch to {title}.")
            elif barge and barge.get("type") == "answer":
                await self._learning.record(
                    InteractionEvent(
                        checkout_id=cid,
                        node_id=prev_id,
                        event_type="explained_back",
                        payload={"text": barge.get("text", "")},
                    )
                )

            yield _ev("status", phase="step", detail=title)
            node, events = await self._materialize(cid, title, message, user_id=owner)
            for e in events:
                yield e

            if prev_id is not None and prev_id != node.id:
                edge = await self._content.add_edge(
                    prev_id, node.id, "next_in_spine", origin="ai_generated"
                )
                yield _ev(
                    "edge.create",
                    edge={
                        "id": str(edge.id),
                        "src_node": str(edge.src_node),
                        "dst_node": str(edge.dst_node),
                        "type": edge.type,
                    },
                )

            await self._learning.record(
                InteractionEvent(
                    checkout_id=cid, node_id=node.id, event_type="viewed", payload={}
                )
            )
            prev_id = node.id
            produced += 1

        await self._library.merge_companion_memory(
            cid, {"last_subject": message, "nodes_produced": produced}
        )
        yield _ev("done", nodes=produced)

    async def pull_thread(
        self, checkout_id: UUID, node_id: UUID
    ) -> AsyncIterator[StreamEvent]:
        """Spawn a rabbit-hole branch off an existing node."""
        cid, anchor = UUID(str(checkout_id)), UUID(str(node_id))
        owner = await self._library.checkout_owner(cid)
        sub = await self._content.get_subgraph([anchor], depth=0)
        anchor_node = sub.nodes[0]
        yield _ev("status", phase="rabbit_hole", detail=anchor_node.title)

        title = f"A deeper look at {anchor_node.title}"
        node, events = await self._materialize(
            cid, title, anchor_node.title, user_id=owner
        )
        for e in events:
            yield e

        edge = await self._content.add_edge(
            anchor, node.id, "rabbit_hole", origin="ai_generated"
        )
        yield _ev(
            "edge.create",
            edge={
                "id": str(edge.id),
                "src_node": str(edge.src_node),
                "dst_node": str(edge.dst_node),
                "type": edge.type,
            },
        )
        await self._learning.record(
            InteractionEvent(
                checkout_id=cid,
                node_id=node.id,
                event_type="rabbit_hole_followed",
                payload={},
            )
        )
        yield _ev("done", nodes=1)

    async def explore_question(
        self, checkout_id: UUID, node_id: UUID
    ) -> AsyncIterator[StreamEvent]:
        """A `question` node is a generation seed (Phase 5 §5): build the concepts
        that answer it rather than serving a body. Each generated concept is linked
        back to the question with an `answers` edge."""
        cid, qid = UUID(str(checkout_id)), UUID(str(node_id))
        owner = await self._library.checkout_owner(cid)
        question = (await self._content.get_subgraph([qid], depth=0)).nodes[0]
        yield _ev(
            "status",
            phase="answering",
            detail=f"Building an answer to: {question.title}",
        )

        plan = await self._planner.plan(
            question.hook or question.title, checkout_id=cid, user_id=owner
        )
        produced = 0
        for title in plan[: self._s.companion_max_steps]:
            node, events = await self._materialize(
                cid, title, question.title, user_id=owner
            )
            for e in events:
                yield e
            if node.id != qid:
                edge = await self._content.add_edge(
                    node.id, qid, "answers", origin="ai_generated"
                )
                yield _ev(
                    "edge.create",
                    edge={
                        "id": str(edge.id),
                        "src_node": str(edge.src_node),
                        "dst_node": str(edge.dst_node),
                        "type": edge.type,
                    },
                )
            await self._learning.record(
                InteractionEvent(
                    checkout_id=cid, node_id=node.id, event_type="viewed", payload={}
                )
            )
            produced += 1
        yield _ev("done", nodes=produced)

    async def explain_node(
        self, checkout_id: UUID, node_id: UUID
    ) -> AsyncIterator[StreamEvent]:
        """Deep-dive on an existing card: stream a conversational explanation of
        the node itself (ephemeral talk), then generate study materials that
        persist into the library (a key-points summary, an analogy, follow-ups).

        `say` events for the explanation carry `node_id` so the frontend can pin
        the narration to the card that was opened.
        """
        cid, nid = UUID(str(checkout_id)), UUID(str(node_id))
        owner = await self._library.checkout_owner(cid)
        node = (await self._content.get_subgraph([nid], depth=0)).nodes[0]
        yield _ev("status", phase="explaining", detail=node.title)

        # 1) streamed explanation — flush whole sentences so TTS reads naturally.
        buf = ""
        async for chunk in self._elaborator.explain(node):
            buf += chunk
            buf, sentences = _flush_sentences(buf)
            for s in sentences:
                yield _ev("say", text=s, node_id=str(nid))
        tail = _sanitize(buf).strip()
        if tail:
            yield _ev("say", text=tail, node_id=str(nid))

        # 2) study materials -> persist through the canonicalize chokepoint, each
        # linked back to the source node so they replay and grow the graph.
        yield _ev("status", phase="materials", detail="capturing key points…")
        materials = await self._elaborator.materials(
            node, checkout_id=cid, user_id=owner
        )
        produced = 0
        for candidate in materials:
            mat, events = await self._persist_candidate(candidate)
            for e in events:
                yield e
            if mat.id != nid:
                # material -> source: a question is *about* the concept; a summary
                # or analogy *elaborates* it.
                edge_type = "about" if candidate.kind == "question" else "elaborates"
                edge = await self._content.add_edge(
                    mat.id, nid, edge_type, origin="ai_generated"
                )
                yield _ev(
                    "edge.create",
                    edge={
                        "id": str(edge.id),
                        "src_node": str(edge.src_node),
                        "dst_node": str(edge.dst_node),
                        "type": edge.type,
                    },
                )
            produced += 1

        await self._learning.record(
            InteractionEvent(
                checkout_id=cid, node_id=nid, event_type="deep_dive", payload={}
            )
        )
        yield _ev("done", nodes=produced)

    # -- per-step: reuse or generate -----------------------------------------

    async def _materialize(
        self,
        checkout_id: UUID,
        title: str,
        subject: str,
        *,
        user_id: UUID | None = None,
    ) -> tuple[Node, list[StreamEvent]]:
        """Return the resolved canonical node + the events to emit for it."""
        events: list[StreamEvent] = []
        # Reuse on an exact canonical-key hit (definitive) or a strong semantic
        # match. Exact-key mirrors the canonicalizer and is robust even though node
        # embeddings encode hook+body rather than the bare title.
        existing = await self._content.get_node_by_key(normalize_key(title))
        if existing is None:
            hits = await self._library.search(title, k=1)
            if hits and hits[0].score >= self._s.companion_reuse_threshold:
                existing = hits[0].node
        if existing is not None:
            events.append(
                _ev(
                    "say",
                    text=f"You've seen this — {existing.title}. Let's revisit it.",
                )
            )
            events.append(
                _ev(
                    "node.create",
                    temp_id=str(existing.id),
                    node=_node_payload(existing),
                    reused=True,
                )
            )
            return existing, events

        # gap -> generate, ground, optimistic render, then canonicalize
        candidate = await self._generator.generate(
            title, subject, checkout_id=checkout_id, user_id=user_id
        )
        candidate = await self._researcher.ground(
            candidate, checkout_id=checkout_id, user_id=user_id
        )
        events.append(_ev("say", text=f"Here's a new idea: {title}."))
        node, persist_events = await self._persist_candidate(candidate)
        events.extend(persist_events)
        return node, events

    async def _persist_candidate(
        self, candidate: CandidateNode
    ) -> tuple[Node, list[StreamEvent]]:
        """Optimistic render -> canonicalize -> reconcile. The single path every
        generated artifact takes into the library (the canonicalize chokepoint)."""
        events: list[StreamEvent] = []
        temp_id = str(uuid4())
        events.append(
            _ev("node.create", temp_id=temp_id, node=_candidate_payload(candidate))
        )
        result = await self._ingestion.canonicalize(candidate)
        node = result.node
        flagged = node.confidence < self._s.companion_confidence_floor
        events.append(
            _ev(
                "node.update",
                temp_id=temp_id,
                canonical_id=str(node.id),
                patch={
                    "action": result.action,
                    "origin": node.origin,
                    "confidence": node.confidence,
                    "locked": node.locked,
                    "flagged_low_confidence": flagged,
                },
            )
        )
        if flagged:
            events.append(
                _ev(
                    "status",
                    phase="flagged",
                    detail=f"{node.title} is below the confidence floor",
                )
            )
        return node, events


def _drain(inbox: asyncio.Queue | None) -> dict | None:
    if inbox is None:
        return None
    try:
        return inbox.get_nowait()
    except asyncio.QueueEmpty:
        return None


# Back-compat aliases for deps.py during the stub→real swap.
StubCompanion = Companion
StubLLM = LLMGateway

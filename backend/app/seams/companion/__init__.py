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
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

from ...config import Settings, get_settings
from ...ports import CandidateNode, InteractionEvent, Node, StreamEvent
from ..ingestion import normalize_key
from .agents import NodeGenerator, Planner, Researcher
from .llm import FakeLLM, LLMGateway, OllamaChat  # noqa: F401  (re-exported)

log = logging.getLogger("axon.companion")


def _ev(type_: str, **data) -> StreamEvent:
    return StreamEvent(type=type_, data=data)


def _node_payload(node: Node) -> dict:
    return {
        "id": str(node.id),
        "canonical_key": node.canonical_key,
        "title": node.title,
        "hook": node.hook,
        "body": node.body,
        "origin": node.origin,
        "confidence": node.confidence,
        "locked": node.locked,
    }


def _candidate_payload(c: CandidateNode) -> dict:
    return {"title": c.title, "hook": c.hook, "body": c.body, "origin": c.origin}


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

    # -- main loop ------------------------------------------------------------

    async def run_turn(
        self, checkout_id: UUID, message: str, inbox: asyncio.Queue | None = None
    ) -> AsyncIterator[StreamEvent]:
        cid = UUID(str(checkout_id))
        yield _ev("status", phase="planning", detail="checking the library…")
        plan = await self._planner.plan(message)

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
            node, events = await self._materialize(cid, title, message)
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
        sub = await self._content.get_subgraph([anchor], depth=0)
        anchor_node = sub.nodes[0]
        yield _ev("status", phase="rabbit_hole", detail=anchor_node.title)

        title = f"A deeper look at {anchor_node.title}"
        node, events = await self._materialize(cid, title, anchor_node.title)
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

    # -- per-step: reuse or generate -----------------------------------------

    async def _materialize(
        self, checkout_id: UUID, title: str, subject: str
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
        candidate = await self._generator.generate(title, subject)
        candidate = await self._researcher.ground(candidate)
        temp_id = str(uuid4())
        events.append(_ev("say", text=f"Here's a new idea: {title}."))
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

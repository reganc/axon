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
from collections import deque
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

from ...config import Settings, get_settings
from ...ports import CandidateNode, InteractionEvent, Node, StreamEvent
from ..ingestion import normalize_key
from . import media_validation as mv
from .agents import (
    Conversationalist,
    Diagrammer,
    Elaborator,
    MediaScout,
    NodeGenerator,
    Planner,
    Researcher,
)
from .llm import FakeLLM, GatewayChat, LLMGateway  # noqa: F401  (re-exported)

log = logging.getLogger("axon.companion")

# The fast gateway injects web-search/RAG context and leaves markup in prose:
# citation markers ([W2]/[L1]), markdown links, emphasis/inline-code ticks, and
# list/heading leaders. Piper voices any leftover symbol literally — that, plus
# doubled spaces and a space before punctuation, is what makes narration sound
# garbled. Strip it all and normalize whitespace before the text reaches TTS.
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")  # [label](url) -> label
_CITATION = re.compile(r"\[[A-Za-z]?\d+\]")  # [W2], [L1], [3]
_LIST_LEAD = re.compile(r"(?m)^[ \t]*(?:[-*+•>]+|#{1,6})[ \t]+")  # bullets/headings
_EMPHASIS = re.compile(r"[*_`]{1,3}")  # bold / italic / inline-code ticks
_WS = re.compile(r"\s+")  # collapse runs of whitespace (incl. newlines)
_SPACE_PUNCT = re.compile(r" +([.,!?;:])")  # drop the space before punctuation
# A sentence boundary: terminal punctuation followed by whitespace.
_SENTENCE = re.compile(r"(.+?[.!?])(\s+)", re.DOTALL)


def _sanitize(text: str) -> str:
    """Strip gateway/markdown markup and normalize whitespace so the TTS voice
    never tries to pronounce a stray symbol (the usual cause of garbled audio)."""
    text = _MD_LINK.sub(r"\1", text)
    text = _CITATION.sub("", text)
    text = _LIST_LEAD.sub("", text)
    text = _EMPHASIS.sub("", text)
    text = _WS.sub(" ", text)
    text = _SPACE_PUNCT.sub(r"\1", text)
    return text.strip()


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
        "attributes": node.attributes,
    }


def _candidate_payload(c: CandidateNode) -> dict:
    return {
        "title": c.title,
        "kind": c.kind,
        "hook": c.hook,
        "body": c.body,
        "origin": c.origin,
    }


# Cards the companion derives from other cards carry these title prefixes. Two
# consequences flow from recognizing them:
#   * opening one explains it in place but never spawns another round of study
#     materials — a derived card is a leaf, not a concept to mine again, and
#   * "go deeper" peels them off so the new branch names the underlying concept
#     instead of compounding ("A deeper look at A deeper look at …").
_DEEPER_PREFIX = "A deeper look at "
_DERIVED_PREFIXES = (_DEEPER_PREFIX, "Key points: ", "Analogy: ")


def _core_title(title: str) -> str:
    """Peel derived-material prefixes off a title so a follow-up names the real
    concept. Idempotent, and unwinds any accidental nesting from earlier bugs."""
    out = title.strip()
    changed = True
    while changed:
        changed = False
        for prefix in _DERIVED_PREFIXES:
            if out.startswith(prefix):
                out = out[len(prefix) :].strip()
                changed = True
    return out or title.strip()


def _is_derived(node: Node) -> bool:
    """A terminal card: a persisted study artifact (Key points / Analogy) or a
    rabbit-hole 'deeper look' node. Opening it explains in place; it is never
    itself mined for further materials."""
    return node.kind == "artifact" or node.title.startswith(_DEEPER_PREFIX)


def _neighbor_graph(anchor_id: UUID, sub) -> dict:
    """A compact, render-ready neighborhood for the card's mini-graph, capped so
    the payload stays small even for a richly connected node."""
    nodes = [
        {"id": str(n.id), "title": n.title, "kind": n.kind} for n in sub.nodes[:13]
    ]
    keep = {n["id"] for n in nodes}
    edges = [
        {"src": str(e.src_node), "dst": str(e.dst_node), "type": e.type}
        for e in sub.edges
        if str(e.src_node) in keep and str(e.dst_node) in keep
    ][:24]
    return {"anchor": str(anchor_id), "nodes": nodes, "edges": edges}


def _edge_event(edge) -> StreamEvent:
    return _ev(
        "edge.create",
        edge={
            "id": str(edge.id),
            "src_node": str(edge.src_node),
            "dst_node": str(edge.dst_node),
            "type": edge.type,
        },
    )


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
        self._conversationalist = Conversationalist(llm, self._s)
        self._media_scout = MediaScout(llm, self._s)
        self._diagrammer = Diagrammer(llm, self._s)

    # -- main loop ------------------------------------------------------------

    async def run_turn(
        self, checkout_id: UUID, message: str, inbox: asyncio.Queue | None = None
    ) -> AsyncIterator[StreamEvent]:
        cid = UUID(str(checkout_id))
        owner = await self._library.checkout_owner(cid)
        yield _ev("status", phase="planning", detail="checking the library…")
        plan = await self._planner.plan(message, checkout_id=cid, user_id=owner)
        if plan:
            # One lead-in line, then just the titles as each card lands — no
            # per-card preamble, so the run reads as a smooth list.
            yield _ev("say", text="Some items you might find interesting.")

        # Materialize a few upcoming nodes concurrently (each is a local draft
        # then a cloud grounding pass) while emitting strictly in plan order, so
        # one node's grounding overlaps the next's drafting instead of running the
        # whole pipeline serially. Interrupts still swap only the *current* step
        # and leave the rest of the plan intact, matching the serial behaviour.
        width = max(1, self._s.companion_generate_concurrency)
        upcoming = iter(plan)
        pending: deque[tuple[str, asyncio.Task]] = deque()
        inflight: set[asyncio.Task] = set()

        def _launch(title: str) -> asyncio.Task:
            task = asyncio.create_task(
                self._materialize(cid, title, message, user_id=owner)
            )
            inflight.add(task)
            return task

        def _fill() -> None:
            while len(pending) < width:
                nxt = next(upcoming, None)
                if nxt is None:
                    return
                pending.append((nxt, _launch(nxt)))

        prev_id: UUID | None = None
        produced = 0
        try:
            _fill()
            while pending:
                barge = _drain(inbox)
                if barge and barge.get("type") == "interrupt":
                    redirect = (barge.get("text") or "").strip()
                    if redirect:
                        # Swap just the head; its speculative draft is abandoned
                        # (cancelling rolls back any in-progress canonicalize).
                        _old_title, old_task = pending.popleft()
                        old_task.cancel()
                        pending.appendleft((redirect, _launch(redirect)))
                        yield _ev("say", text=f"Sure — let's switch to {redirect}.")
                elif barge and barge.get("type") == "answer":
                    await self._learning.record(
                        InteractionEvent(
                            checkout_id=cid,
                            node_id=prev_id,
                            event_type="explained_back",
                            payload={"text": barge.get("text", "")},
                        )
                    )

                title, task = pending.popleft()
                yield _ev("status", phase="step", detail=title)
                node, events = await task
                inflight.discard(task)
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
                        checkout_id=cid,
                        node_id=node.id,
                        event_type="viewed",
                        payload={},
                    )
                )
                prev_id = node.id
                produced += 1
                _fill()
        finally:
            # Abandoned (interrupt) and not-yet-consumed (early disconnect) drafts:
            # cancel and drain so their transactions roll back cleanly.
            for task in inflight:
                task.cancel()
            if inflight:
                await asyncio.gather(*inflight, return_exceptions=True)

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

        # Deepen the underlying concept, not the meta-wrapper: pulling a thread
        # off "A deeper look at Analogy: X" should go after X, not stack another
        # "A deeper look at" in front of it.
        core = _core_title(anchor_node.title)
        title = f"{_DEEPER_PREFIX}{core}"
        node, events = await self._materialize(cid, title, core, user_id=owner)
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
        the node itself (ephemeral talk), then — for concept cards only —
        generate study materials that persist into the library (a key-points
        summary, an analogy, follow-ups). Derived cards (artifacts, rabbit-hole
        'deeper look' nodes) are terminal: explained in place, never mined again.

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

        # Derived cards are leaves: a study artifact (Key points / Analogy) or a
        # rabbit-hole "deeper look" node. Explaining one in place is the whole
        # interaction — mining it again compounds meta-garbage ("Key points:
        # Analogy: …", "A deeper look at A deeper look at …"), so we accrete
        # study materials only off real concepts.
        if _is_derived(node):
            await self._learning.record(
                InteractionEvent(
                    checkout_id=cid, node_id=nid, event_type="deep_dive", payload={}
                )
            )
            yield _ev("done", nodes=0)
            return

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

    async def discuss(
        self, checkout_id: UUID, node_id: UUID, message: str
    ) -> AsyncIterator[StreamEvent]:
        """A node-scoped, multi-turn follow-up — the discussion layer.

        Streams a conversational answer pinned to the card (spoken if voice is on),
        carrying the prior turns of this card's chat as continuity. If the exchange
        surfaces a *genuinely new* concept, it accretes as a linked card through the
        canonicalize chokepoint (reusing an existing node when the library already
        holds it); pure clarifications stay ephemeral talk. The learner's own turn
        is echoed as a `discuss` event so the durable log replays both sides.
        """
        cid, nid = UUID(str(checkout_id)), UUID(str(node_id))
        owner = await self._library.checkout_owner(cid)
        node = (await self._content.get_subgraph([nid], depth=0)).nodes[0]

        # History before the echo, so the current message isn't double-counted.
        history = await self._discussion_history(cid, nid)
        yield _ev("discuss", node_id=str(nid), role="learner", text=message)

        # 1) streamed answer — whole sentences so TTS reads naturally; pinned to
        #    the card via node_id (same path the deep-dive narration uses).
        buf = ""
        parts: list[str] = []
        async for chunk in self._conversationalist.reply(node, history, message):
            buf += chunk
            buf, sentences = _flush_sentences(buf)
            for s in sentences:
                parts.append(s)
                yield _ev("say", text=s, node_id=str(nid))
        tail = _sanitize(buf).strip()
        if tail:
            parts.append(tail)
            yield _ev("say", text=tail, node_id=str(nid))
        answer = " ".join(parts)

        await self._learning.record(
            InteractionEvent(
                checkout_id=cid,
                node_id=nid,
                event_type="discussed",
                payload={"message": message},
            )
        )

        # 2) auto-accrete: did the exchange surface a genuinely new concept? If so,
        #    build it (reuse-or-generate+ground) and link it back to this card.
        candidate = await self._conversationalist.extract_concept(
            node, message, answer, checkout_id=cid, user_id=owner
        )
        if candidate is not None:
            new_node, events = await self._materialize(
                cid, candidate.title, node.title, user_id=owner
            )
            for e in events:
                yield e
            if new_node.id != nid:
                edge = await self._content.add_edge(
                    new_node.id, nid, "elaborates", origin="ai_generated"
                )
                yield _edge_event(edge)
            await self._learning.record(
                InteractionEvent(
                    checkout_id=cid,
                    node_id=new_node.id,
                    event_type="rabbit_hole_followed",
                    payload={"via": "discuss"},
                )
            )
        yield _ev("done")

    async def enrich(
        self, checkout_id: UUID, node_id: UUID
    ) -> AsyncIterator[StreamEvent]:
        """Surface visual aids for a card — the visual layer. Emits `media` events
        (each recorded in the durable log, so they replay on reconnect):

        1. a neighbor mini-graph drawn straight from the canonical graph (no LLM);
        2. a generated Mermaid diagram of the concept's structure;
        3. real web media (an explainer video, reference links, an image) found via
           the gateway's web search.

        Every external reference is resolved (`media_validation`) before it reaches
        the learner — a dead or fabricated URL is dropped, not rendered.
        """
        cid, nid = UUID(str(checkout_id)), UUID(str(node_id))
        owner = await self._library.checkout_owner(cid)
        sub = await self._content.get_subgraph([nid], depth=1)
        node = next((n for n in sub.nodes if n.id == nid), None)
        if node is None:
            return
        # No `status`/`done` here on purpose: enrichment is a background side-channel
        # that streams `media` events into the open card. Emitting `done` would clear
        # the shared `busy` flag and cut a concurrent deep-dive's "thinking" cue short.

        # 1) neighbor mini-graph (canonical, no model call)
        graph = _neighbor_graph(nid, sub)
        if graph["edges"]:
            yield _ev("media", node_id=str(nid), media_kind="graph", graph=graph)

        # 2) generated structural diagram, gated on valid Mermaid syntax
        mermaid = await self._diagrammer.diagram(node, checkout_id=cid, user_id=owner)
        if mv.validate_mermaid(mermaid):
            yield _ev("media", node_id=str(nid), media_kind="diagram", mermaid=mermaid)

        # 3) real web media — each candidate resolved before it's surfaced
        found = await self._media_scout.find(node, checkout_id=cid, user_id=owner)
        for url in found["videos"]:
            if await mv.validate_youtube(url):
                yield _ev("media", node_id=str(nid), media_kind="video", url=url)
        for link in found["links"]:
            if await mv.validate_link(link["url"]):
                yield _ev(
                    "media",
                    node_id=str(nid),
                    media_kind="link",
                    url=link["url"],
                    title=link["title"],
                )
        for url in found["images"]:
            if await mv.validate_image(url):
                yield _ev("media", node_id=str(nid), media_kind="image", url=url)

        await self._learning.record(
            InteractionEvent(
                checkout_id=cid, node_id=nid, event_type="enriched", payload={}
            )
        )

    async def _discussion_history(self, cid: UUID, nid: UUID) -> list[dict]:
        """Reconstruct this card's prior turns from the durable conversation log:
        the learner's `discuss` turns and the Tutor's `say` lines pinned to the
        node (deep-dive narration + earlier answers), in order. Consecutive Tutor
        sentences collapse into one turn so the model sees coherent exchanges."""
        events = await self._library.get_conversation(cid)
        target = str(nid)
        turns: list[dict] = []
        for ev in events:
            if ev.type == "discuss" and ev.data.get("node_id") == target:
                turns.append({"role": "learner", "text": ev.data.get("text", "")})
            elif ev.type == "say" and ev.data.get("node_id") == target:
                text = ev.data.get("text", "")
                if turns and turns[-1]["role"] == "tutor":
                    turns[-1]["text"] += " " + text
                else:
                    turns.append({"role": "tutor", "text": text})
        return turns

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
            events.append(_ev("say", text=existing.title))
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
        events.append(_ev("say", text=title))
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

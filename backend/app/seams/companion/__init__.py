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
from ...ports import (
    CandidateNode,
    ConversationEvent,
    InteractionEvent,
    Msg,
    Node,
    StreamEvent,
)
from ..ingestion import normalize_key
from . import cache
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


def _speakable_sentences(text: str) -> list[str]:
    """Split a complete text into sanitized sentences for narration (the
    non-streaming counterpart of _flush_sentences — the tail is kept)."""
    rest, sentences = _flush_sentences(text)
    tail = _sanitize(rest).strip()
    return [*sentences, tail] if tail else sentences


def _ev(type_: str, **data) -> StreamEvent:
    return StreamEvent(type=type_, data=data)


# Mastery bands for prompt conditioning. The *band* (not the raw float) keys the
# dive cache, so personalization stays coarse enough to share cached dives.
# Only three bands, and "default" covers both new and developing learners: mere
# engagement (a view, a dive) must not change the band, or a card would miss
# its own cache on reopen. "shaky" needs *negative evidence* — recorded
# confusion — not just low mastery; "strong" needs real demonstrated grasp.
_MASTERY_SHAKY = 0.35
_MASTERY_STRONG = 0.70


def _mastery_band(mastery: float | None, confusions: int = 0) -> str:
    if mastery is not None and mastery >= _MASTERY_STRONG:
        return "strong"
    if mastery is not None and confusions > 0 and mastery < _MASTERY_SHAKY:
        return "shaky"
    return "default"


def _band_clause(band: str) -> str:
    """How the focal node's mastery band shapes the talk. 'default' gets the
    baseline register — no clause."""
    return {
        "shaky": (
            " This learner has struggled with this concept before — rebuild it "
            "gently from first principles and check the intuition as you go."
        ),
        "strong": (
            " This learner already has a solid grasp of this concept — skip "
            "the basics and go straight to depth, nuance, and edge cases."
        ),
    }.get(band, "")


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
        dive_cache=None,
    ) -> None:
        self._s = settings or get_settings()
        self._llm = llm
        self._library = library
        self._ingestion = ingestion
        self._content = content
        self._learning = learning
        # Optional deep-dive cache (see cache.py). None -> every dive streams
        # fresh; deps.py wires the Redis-backed cache in production.
        self._dive_cache = dive_cache
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
        # Each item streams its events through a queue so the head card renders
        # the moment its draft exists — grounding resolves behind it.
        width = max(1, self._s.companion_generate_concurrency)
        upcoming = iter(plan)
        pending: deque[tuple[str, asyncio.Queue, asyncio.Task]] = deque()
        inflight: set[asyncio.Task] = set()

        def _launch(title: str) -> tuple[asyncio.Queue, asyncio.Task]:
            q: asyncio.Queue = asyncio.Queue()

            async def _run() -> Node:
                try:
                    node, _ = await self._materialize(
                        cid, title, message, user_id=owner, sink=q.put_nowait
                    )
                    return node
                finally:
                    q.put_nowait(None)  # sentinel: no more events for this item

            task = asyncio.create_task(_run())
            inflight.add(task)
            return q, task

        def _fill() -> None:
            while len(pending) < width:
                nxt = next(upcoming, None)
                if nxt is None:
                    return
                pending.append((nxt, *_launch(nxt)))

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
                        _old_title, _old_q, old_task = pending.popleft()
                        old_task.cancel()
                        pending.appendleft((redirect, *_launch(redirect)))
                        yield _ev("say", text=f"Sure — let's switch to {redirect}.")
                elif barge and barge.get("type") == "answer":
                    await self._track(
                        cid,
                        prev_id,
                        "explained_back",
                        {"text": barge.get("text", "")},
                    )

                title, q, task = pending.popleft()
                yield _ev("status", phase="step", detail=title)
                while (e := await q.get()) is not None:
                    yield e
                node = await task
                inflight.discard(task)

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

                await self._track(cid, node.id, "viewed")
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
        await self._track(cid, node.id, "rabbit_hole_followed")
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
            await self._track(cid, node.id, "viewed")
            produced += 1
        yield _ev("done", nodes=produced)

    async def explain_node(
        self,
        checkout_id: UUID,
        node_id: UUID,
        level: str | None = None,
        depth: int = 0,
    ) -> AsyncIterator[StreamEvent]:
        """Deep-dive on an existing card: read the card itself (hook + notes),
        stream a conversational explanation beyond it (ephemeral talk), then —
        for concept cards only — generate study materials that persist into the
        library (a key-points summary, an analogy, follow-ups). Derived cards
        (artifacts, rabbit-hole 'deeper look' nodes) are terminal: explained in
        place, never mined again.

        `depth` is the go-deeper ladder: 0 is the first pass; each increment
        generates a genuinely deeper pass (routed to the reasoning model,
        given the prior narration and graph neighbors, cached per rung).

        `say` events for the explanation carry `node_id` so the frontend can pin
        the narration to the card that was opened.
        """
        cid, nid = UUID(str(checkout_id)), UUID(str(node_id))
        depth = max(0, min(int(depth or 0), self._s.companion_max_dive_depth))
        owner, sub, ctx = await asyncio.gather(
            self._library.checkout_owner(cid),
            self._content.get_subgraph([nid], depth=1),
            self._learning.learner_context(cid, nid),
        )
        node = next(n for n in sub.nodes if n.id == nid)
        neighbor_titles = tuple(n.title for n in sub.nodes if n.id != nid)[:8]
        yield _ev(
            "status",
            phase="explaining",
            detail=node.title if depth == 0 else f"digging deeper: {node.title}",
        )

        # How well does this learner know this card already? The coarse band
        # shapes the talk (and keys the cache) — shaky learners get first
        # principles, strong ones get depth.
        band = _mastery_band(ctx.focus_mastery, ctx.focus_confusions)

        # Cache check: a dive for this exact node content + level + mastery band
        # + depth rung may already exist (this or any other session). A hit
        # narrates instantly and replays the material cards from the DB — zero
        # LLM calls.
        key = cache.dive_key(
            nid,
            level,
            f"{node.title}\n{node.hook or ''}\n{node.body or ''}",
            band=band,
            depth=depth,
        )
        hit = await self._dive_cache.get(key) if self._dive_cache else None
        if hit is not None:
            async for ev in self._replay_dive(cid, nid, hit):
                yield ev
            return

        # 1) the card itself first — hook, then the notes — but only on the
        #    first pass. The learner opened this card to hear *it*; the
        #    generated elaboration below builds beyond the notes instead of
        #    replacing them. Included in `spoken` so cached replays read the
        #    card too. Deeper rungs skip straight to new material.
        spoken: list[str] = []
        if depth == 0:
            for text in (node.hook, node.body):
                for s in _speakable_sentences(text or ""):
                    spoken.append(s)
                    yield _ev("say", text=s, node_id=str(nid))

        # What was already said about this card (earlier rungs + discussion),
        # so a deeper pass advances instead of repeating. From the durable log,
        # capped so the prompt stays bounded.
        prior = ""
        if depth > 0:
            turns = await self._discussion_history(cid, nid)
            prior = " ".join(t["text"] for t in turns if t["role"] == "tutor")[-1500:]

        # 2) streamed explanation — flush whole sentences so TTS reads naturally.
        #    `level` shapes only this ephemeral talk; the study materials below
        #    persist at the canonical register regardless of the learner's level.
        buf = ""
        async for chunk in self._elaborator.explain(
            node,
            level=level,
            learner_clause=_band_clause(band),
            depth=depth,
            neighbor_titles=neighbor_titles,
            prior=prior,
            checkout_id=cid,
            user_id=owner,
        ):
            buf += chunk
            buf, sentences = _flush_sentences(buf)
            for s in sentences:
                spoken.append(s)
                yield _ev("say", text=s, node_id=str(nid))
        tail = _sanitize(buf).strip()
        if tail:
            spoken.append(tail)
            yield _ev("say", text=tail, node_id=str(nid))

        # Deeper rungs are talk only: the study materials already exist from the
        # first pass — regenerating them would only duplicate.
        if depth > 0:
            await self._track(cid, nid, "deep_dive")
            if self._dive_cache:
                await self._dive_cache.put(
                    key, {"sentences": spoken, "materials": [], "edges": []}
                )
            yield _ev("done", nodes=0)
            return

        # Derived cards are leaves: a study artifact (Key points / Analogy) or a
        # rabbit-hole "deeper look" node. Explaining one in place is the whole
        # interaction — mining it again compounds meta-garbage ("Key points:
        # Analogy: …", "A deeper look at A deeper look at …"), so we accrete
        # study materials only off real concepts.
        if _is_derived(node):
            await self._track(cid, nid, "deep_dive")
            if self._dive_cache:
                await self._dive_cache.put(
                    key, {"sentences": spoken, "materials": [], "edges": []}
                )
            yield _ev("done", nodes=0)
            return

        # 3) study materials -> persist through the canonicalize chokepoint, each
        # linked back to the source node so they replay and grow the graph.
        yield _ev("status", phase="materials", detail="capturing key points…")
        materials = await self._elaborator.materials(
            node, checkout_id=cid, user_id=owner
        )
        produced = 0
        material_ids: list[str] = []
        edge_payloads: list[dict] = []
        for candidate in materials:
            mat, events = await self._persist_candidate(candidate)
            for e in events:
                yield e
            if mat.id != nid:
                material_ids.append(str(mat.id))
                # material -> source: a question is *about* the concept; a summary
                # or analogy *elaborates* it.
                edge_type = "about" if candidate.kind == "question" else "elaborates"
                edge = await self._content.add_edge(
                    mat.id, nid, edge_type, origin="ai_generated"
                )
                edge_payload = {
                    "id": str(edge.id),
                    "src_node": str(edge.src_node),
                    "dst_node": str(edge.dst_node),
                    "type": edge.type,
                }
                edge_payloads.append(edge_payload)
                yield _ev("edge.create", edge=edge_payload)
            produced += 1

        await self._track(cid, nid, "deep_dive")
        # Cache only after the full dive completed — a cancelled stream (card
        # closed, superseded) never caches a truncated explanation.
        if self._dive_cache:
            await self._dive_cache.put(
                key,
                {
                    "sentences": spoken,
                    "materials": material_ids,
                    "edges": edge_payloads,
                },
            )
        yield _ev("done", nodes=produced)

    async def _replay_dive(
        self, cid: UUID, nid: UUID, hit: dict
    ) -> AsyncIterator[StreamEvent]:
        """Serve a cached deep-dive: narration sentence-by-sentence, then the
        material cards re-surfaced from the DB as reuse events — so a fresh
        checkout's deck still gets the cards. Materials that have since been
        purged are silently skipped. Zero LLM calls."""
        for s in hit.get("sentences") or []:
            yield _ev("say", text=s, node_id=str(nid))
        ids = [UUID(m) for m in hit.get("materials") or []]
        if ids:
            sub = await self._content.get_subgraph(ids, depth=0)
            known = {str(n.id) for n in sub.nodes} | {str(nid)}
            for n in sub.nodes:
                if n.id == nid:
                    continue
                yield _ev(
                    "node.create",
                    temp_id=str(n.id),
                    node=_node_payload(n),
                    reused=True,
                )
            for e in hit.get("edges") or []:
                if e.get("src_node") in known and e.get("dst_node") in known:
                    yield _ev("edge.create", edge=e)
        await self._track(cid, nid, "deep_dive")
        yield _ev("done", nodes=0)

    async def discuss(
        self, checkout_id: UUID, node_id: UUID, message: str, level: str | None = None
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
        # The pre-answer reads are independent — one round-trip's latency, not
        # four, before the first spoken word. History is read before the echo,
        # so the current message isn't double-counted.
        owner, sub, history, ctx = await asyncio.gather(
            self._library.checkout_owner(cid),
            self._content.get_subgraph([nid], depth=0),
            self._discussion_history(cid, nid),
            self._learning.learner_context(cid, nid),
        )
        node = sub.nodes[0]
        yield _ev("discuss", node_id=str(nid), role="learner", text=message)

        # Personal context for the reply: discussion is uncached and one-to-one,
        # so it gets the full read — focal mastery band plus the learner's
        # weak/strong neighboring concepts.
        learner = await self._learner_clause(ctx)

        # 1) streamed answer — whole sentences so TTS reads naturally; pinned to
        #    the card via node_id (same path the deep-dive narration uses).
        buf = ""
        parts: list[str] = []
        async for chunk in self._conversationalist.reply(
            node, history, message, level=level, learner_clause=learner
        ):
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

        await self._track(cid, nid, "discussed", {"message": message})
        # The answer is complete — release the learner's "thinking" cue now.
        # Auto-accretion below is housekeeping; its cards stream in afterwards.
        yield _ev("done")

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

    async def mine_session(self, checkout_id: UUID) -> int:
        """Distill the learner's live dialogue into the library — the dialogue side
        of the self-augmenting loop (companion-generated nodes already accrete; the
        learner's own words did not until now).

        Reads the durable conversation, builds a learner/tutor transcript from the
        turns added since the last mined watermark, and — only if the learner
        actually spoke — runs it through the ingestion miner (segment -> extract ->
        ground -> canonicalize). Idempotent: the canonicalize chokepoint dedups and
        the per-checkout watermark stops a reconnect from re-mining settled turns.
        Returns the number of nodes created or merged.
        """
        cid = UUID(str(checkout_id))
        events = await self._library.get_conversation(cid)
        memory = await self._library.read_companion_memory(cid)
        mined_through = int(memory.get("mined_through", 0) or 0)
        if mined_through >= len(events):
            return 0  # nothing new since the last close

        turns = _session_turns(events[mined_through:])
        if not any(t.role == "user" for t in turns):
            # No fresh learner words to distil — the tutor's nodes already
            # canonicalized live. Advance the watermark so we don't re-scan them.
            await self._library.merge_companion_memory(
                cid, {"mined_through": len(events)}
            )
            return 0

        report = await self._ingestion.mine_turns(turns, f"session-{cid}")
        await self._library.merge_companion_memory(cid, {"mined_through": len(events)})
        return report.nodes + report.merged

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
        sink=None,
    ) -> tuple[Node, list[StreamEvent]]:
        """Resolve one concept: reuse, or generate -> optimistic render ->
        ground -> canonicalize. Events flow to `sink` the moment they are
        produced (so a live consumer renders the card before grounding
        finishes); with no sink they accumulate and return as a list."""
        events: list[StreamEvent] = []
        emit = sink or events.append
        # Reuse on an exact canonical-key hit (definitive) or a strong semantic
        # match. Exact-key mirrors the canonicalizer and is robust even though node
        # embeddings encode hook+body rather than the bare title.
        existing = await self._content.get_node_by_key(normalize_key(title))
        if existing is None:
            hits = await self._library.search(title, k=1)
            if hits and hits[0].score >= self._s.companion_reuse_threshold:
                existing = hits[0].node
        if existing is not None:
            emit(_ev("say", text=existing.title))
            emit(
                _ev(
                    "node.create",
                    temp_id=str(existing.id),
                    node=_node_payload(existing),
                    reused=True,
                )
            )
            return existing, events

        # gap -> generate, render optimistically, then ground + canonicalize.
        # The learner sees the drafted card immediately; grounding (the slow,
        # search-injected local pass) resolves behind it and lands as the
        # node.update — the reconciliation principle the stream already uses
        # for canonical ids (specs/00 #6).
        candidate = await self._generator.generate(
            title, subject, checkout_id=checkout_id, user_id=user_id
        )
        emit(_ev("say", text=title))
        temp_id = str(uuid4())
        emit(_ev("node.create", temp_id=temp_id, node=_candidate_payload(candidate)))
        candidate = await self._researcher.ground(
            candidate, checkout_id=checkout_id, user_id=user_id
        )
        result = await self._ingestion.canonicalize(candidate)
        node = result.node
        flagged = node.confidence < self._s.companion_confidence_floor
        emit(
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
            emit(
                _ev(
                    "status",
                    phase="flagged",
                    detail=f"{node.title} is below the confidence floor",
                )
            )
        return node, events

    async def _track(
        self, cid: UUID, nid: UUID | None, event_type: str, payload: dict | None = None
    ) -> None:
        """Record a learner interaction AND recompute the node's mastery — the
        two must travel together, or events accrete while the mastery model
        never moves (the bug this helper retires)."""
        await self._learning.record(
            InteractionEvent(
                checkout_id=cid,
                node_id=nid,
                event_type=event_type,
                payload=payload or {},
            )
        )
        if nid is not None:
            await self._learning.update_mastery(cid, nid)

    async def _learner_clause(self, ctx) -> str:
        """The full personal clause for *uncached* talk (discussion replies):
        focal-node band plus the learner's weak/strong neighboring concepts,
        titles resolved through the content port."""
        parts: list[str] = []
        band_text = _band_clause(_mastery_band(ctx.focus_mastery, ctx.focus_confusions))
        if band_text:
            parts.append(band_text.strip())
        ids = [nm.node_id for nm in [*ctx.weakest, *ctx.strongest]]
        titles: dict = {}
        if ids:
            sub = await self._content.get_subgraph(ids, depth=0)
            titles = {n.id: n.title for n in sub.nodes}
        weak = [titles[nm.node_id] for nm in ctx.weakest if nm.node_id in titles]
        strong = [titles[nm.node_id] for nm in ctx.strongest if nm.node_id in titles]
        if weak:
            parts.append(
                "They have been struggling with "
                + ", ".join(weak)
                + " — watch for gaps from there."
            )
        if strong:
            parts.append(
                "They are confident with "
                + ", ".join(strong)
                + " — build on those when it helps."
            )
        return (" " + " ".join(parts)) if parts else ""

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


def _session_turns(events: list[ConversationEvent]) -> list[Msg]:
    """Reduce a slice of the durable conversation to a learner/tutor transcript for
    mining: learner `discuss` turns become role='user', the Tutor's `say` lines
    role='assistant', in order. The interleaving keeps each learner question next
    to the answer it provoked, so a span carries enough context to distil one
    concept. Structural events (node/edge) are dropped — they already accreted."""
    turns: list[Msg] = []
    for ev in events:
        if ev.type == "discuss" and ev.data.get("role") == "learner":
            text = (ev.data.get("text") or "").strip()
            if text:
                turns.append(Msg(role="user", content=text))
        elif ev.type == "say":
            text = (ev.data.get("text") or "").strip()
            if text:
                turns.append(Msg(role="assistant", content=text))
    return turns


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

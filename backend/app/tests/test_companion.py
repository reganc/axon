"""companion seam — the Tutor event stream (DB + scripted LLM)."""

from __future__ import annotations

import asyncio
from uuid import uuid4

from app.ports import CandidateNode
from app.seams.ingestion import normalize_key

from .conftest import make_companion, requires_db, scalar
from .test_miner import _extract_ground_handler

pytestmark = requires_db


async def _free_checkout(seams, subject: str):
    return await seams.library.checkout(uuid4(), None, subject)


def _mining_companion(seams, title_for):
    """A companion whose ingestion carries a scripted miner LLM, so mine_session
    can run the extract -> ground -> canonicalize pipeline deterministically."""
    from app.seams.companion import Companion
    from app.seams.companion.llm import LLMGateway
    from app.seams.ingestion import Ingestion

    gateway = LLMGateway.scripted(_extract_ground_handler(title_for), seams.embedder)
    ingestion = Ingestion(content=seams.content, embedder=seams.embedder, llm=gateway)
    return Companion(
        llm=gateway,
        library=seams.library,
        ingestion=ingestion,
        content=seams.content,
        learning=seams.learning,
    )


async def test_run_turn_streams_and_persists_generated_node(seeded, seams):
    subject = "Quantum tunnelling in semiconductor junctions"
    comp = make_companion(seams, plan=[subject], confidence=0.82)
    checkout = await _free_checkout(seams, subject)

    events = [e async for e in comp.run_turn(checkout.id, subject)]
    types = [e.type for e in events]

    assert "say" in types
    assert "node.create" in types
    assert "node.update" in types  # gap -> canonicalize reconciliation
    assert types[-1] == "done"

    # the generated node landed in the library, queryable, grounded by the Researcher
    node = await seams.content.get_node_by_key(normalize_key(subject))
    assert node is not None
    assert node.origin in ("ai_generated", "ai_extended")
    assert abs(node.confidence - 0.82) < 0.02
    # (semantic-ranking quality of search is covered by the Ollama-gated Phase-1 test)


async def test_known_subject_reuses_without_generating(seeded, seams):
    # titles that normalize to seeded canonical keys -> Tutor reuses, never generates
    plan = ["The convolutional network", "Backpropagation"]
    comp = make_companion(seams, plan=plan)
    checkout = await _free_checkout(seams, "convolutional networks")

    before = await scalar("SELECT count(*) FROM canonical_nodes")
    events = [e async for e in comp.run_turn(checkout.id, "convolutional networks")]
    after = await scalar("SELECT count(*) FROM canonical_nodes")

    assert after == before  # nothing new generated
    assert any(e.type == "node.create" and e.data.get("reused") for e in events)
    assert not any(e.type == "node.update" for e in events)


async def test_interrupt_visibly_changes_the_stream(seeded, seams):
    comp = make_companion(seams, plan=["The convolutional network"])
    checkout = await _free_checkout(seams, "CNNs")
    inbox: asyncio.Queue = asyncio.Queue()
    inbox.put_nowait({"type": "interrupt", "text": "Backpropagation"})

    events = [e async for e in comp.run_turn(checkout.id, "CNNs", inbox)]
    says = [e.data.get("text", "") for e in events if e.type == "say"]
    assert any("Backpropagation" in t for t in says)


async def test_run_turn_materializes_in_parallel_but_emits_in_order(seeded, seams):
    """Upcoming nodes are generated+grounded concurrently (the latency win) while
    events still stream strictly in plan order (the spine stays coherent)."""
    plan = [
        "Parallel pipeline topic alpha",
        "Parallel pipeline topic beta",
        "Parallel pipeline topic gamma",
    ]
    comp = make_companion(seams, plan=plan)
    checkout = await _free_checkout(seams, "parallel subjects")

    original = comp._materialize
    active = peak = 0

    async def _instrumented(cid, title, subject, *, user_id=None):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.05)  # hold so concurrent tasks accumulate
            return await original(cid, title, subject, user_id=user_id)
        finally:
            active -= 1

    comp._materialize = _instrumented
    steps = [
        e.data.get("detail")
        async for e in comp.run_turn(checkout.id, "parallel subjects")
        if e.type == "status" and e.data.get("phase") == "step"
    ]

    assert peak >= 2  # ran concurrently, not strictly serially
    assert steps == plan  # yet emitted in exact plan order


async def test_generated_node_never_overwrites_locked_anchor(seeded, seams):
    before = await seams.content.get_node_by_key("cnn-weight-sharing")
    comp = make_companion(seams, plan=["CNN weight sharing"])
    checkout = await _free_checkout(seams, "CNNs")

    async for _ in comp.run_turn(checkout.id, "CNNs"):
        pass

    after = await seams.content.get_node_by_key("cnn-weight-sharing")
    assert after.locked is True
    assert after.version == before.version
    assert after.body == before.body


async def test_unlocked_duplicate_merges_not_duplicates(seeded, seams):
    title = "Synthetic companion test concept alpha"
    first = await seams.ingestion.canonicalize(
        CandidateNode(
            title=title, hook="h1", body="b1", origin="ai_generated", confidence=0.7
        )
    )
    assert first.action == "created"

    before = await scalar("SELECT count(*) FROM canonical_nodes")
    second = await seams.ingestion.canonicalize(
        CandidateNode(
            title=title, hook="h2", body="b2", origin="ai_generated", confidence=0.7
        )
    )
    after = await scalar("SELECT count(*) FROM canonical_nodes")

    assert second.action == "merged"
    assert after == before
    assert second.node.version > first.node.version
    assert second.node.origin == "ai_extended"


async def test_pull_thread_spawns_rabbit_hole(seeded, seams):
    comp = make_companion(seams, plan=[])
    anchor = await seams.content.get_node_by_key("the-convolutional-network")
    checkout = await _free_checkout(seams, "rabbit hole")

    events = [e async for e in comp.pull_thread(checkout.id, anchor.id)]
    types = [e.type for e in events]
    assert "node.create" in types
    assert types[-1] == "done"
    assert any(
        e.type == "edge.create" and e.data["edge"]["type"] == "rabbit_hole"
        for e in events
    )


async def test_explain_node_streams_and_persists_materials(seeded, seams):
    comp = make_companion(seams, plan=[])
    node = await seams.content.get_node_by_key("the-convolutional-network")
    checkout = await _free_checkout(seams, "deep dive")

    before = await scalar("SELECT count(*) FROM canonical_nodes")
    events = [e async for e in comp.explain_node(checkout.id, node.id)]
    after = await scalar("SELECT count(*) FROM canonical_nodes")

    # 1) the explanation streams as several say events pinned to the opened card
    says = [e for e in events if e.type == "say"]
    assert len(says) >= 2
    assert all(e.data.get("node_id") == str(node.id) for e in says)

    # 2) materials persist into the library as new nodes + edges back to the card
    assert after > before
    assert any(e.type == "node.update" for e in events)
    assert any(e.type == "edge.create" for e in events)
    assert events[-1].type == "done"

    # a follow-up question landed as a `question` node linked `about` the concept
    summary = await seams.content.get_node_by_key(
        normalize_key(f"Key points: {node.title}")
    )
    assert summary is not None and summary.kind == "artifact"


async def test_explain_node_narrates_the_card_itself_first(seeded, seams):
    """Opening a card reads the card: its hook and notes are spoken before the
    generated elaboration, so the detail is always narrated even when the
    model's paraphrase is thin."""
    from app.seams.companion import _speakable_sentences

    comp = make_companion(seams, plan=[])
    node = await seams.content.get_node_by_key("the-convolutional-network")
    checkout = await _free_checkout(seams, "narrate the card")

    events = [e async for e in comp.explain_node(checkout.id, node.id)]
    says = [e.data["text"] for e in events if e.type == "say"]

    expected = [
        *_speakable_sentences(node.hook or ""),
        *_speakable_sentences(node.body or ""),
    ]
    assert expected, "seed card should have a hook/body to narrate"
    assert says[: len(expected)] == expected
    assert len(says) > len(expected)  # the elaboration still follows


async def test_explain_node_reopen_serves_from_cache(seeded, seams):
    """A second dive on the same card replays from the cache: identical
    narration, material cards re-surfaced as reuse events, and nothing
    regenerated or re-persisted (no LLM, no canonicalize)."""
    from app.seams.companion.cache import MemoryDiveCache

    dive_cache = MemoryDiveCache()
    comp = make_companion(seams, plan=[], dive_cache=dive_cache)
    node = await seams.content.get_node_by_key("the-convolutional-network")
    checkout = await _free_checkout(seams, "deep dive")

    first = [e async for e in comp.explain_node(checkout.id, node.id)]
    assert len(dive_cache.store) == 1  # the completed dive was captured

    before = await scalar("SELECT count(*) FROM canonical_nodes")
    second = [e async for e in comp.explain_node(checkout.id, node.id)]
    after = await scalar("SELECT count(*) FROM canonical_nodes")

    # narration replays identically, still pinned to the card
    first_says = [e.data["text"] for e in first if e.type == "say"]
    second_says = [e.data["text"] for e in second if e.type == "say"]
    assert second_says == first_says
    assert all(e.data.get("node_id") == str(node.id) for e in second if e.type == "say")

    # material cards re-surface as reuse events; nothing new persists
    assert after == before
    assert any(e.type == "node.create" and e.data.get("reused") for e in second)
    assert any(e.type == "edge.create" for e in second)
    assert not any(e.type == "node.update" for e in second)  # no canonicalize ran
    assert second[-1].type == "done"


async def test_go_deeper_is_a_new_pass_not_a_replay(seeded, seams):
    """depth keys the dive cache: asking to dig deeper streams a fresh pass
    instead of replaying the first one, skips the card-intro narration, and
    accretes no duplicate study materials."""
    from app.seams.companion.cache import MemoryDiveCache

    dive_cache = MemoryDiveCache()
    comp = make_companion(seams, plan=[], dive_cache=dive_cache)
    node = await seams.content.get_node_by_key("the-convolutional-network")
    checkout = await _free_checkout(seams, "go deeper")

    first = [e async for e in comp.explain_node(checkout.id, node.id)]
    before = await scalar("SELECT count(*) FROM canonical_nodes")
    deeper = [e async for e in comp.explain_node(checkout.id, node.id, depth=1)]
    after = await scalar("SELECT count(*) FROM canonical_nodes")

    # separate cache rungs — a reopen at depth 0 still hits, depth 1 is its own
    assert len(dive_cache.store) == 2
    assert any(":d0:" in k for k in dive_cache.store)
    assert any(":d1:" in k for k in dive_cache.store)

    # the deeper pass streamed fresh narration, not the first pass replayed
    first_says = [e.data["text"] for e in first if e.type == "say"]
    deeper_says = [e.data["text"] for e in deeper if e.type == "say"]
    assert deeper_says
    assert deeper_says != first_says
    # and it doesn't re-read the hook/notes intro
    from app.seams.companion import _speakable_sentences

    intro = _speakable_sentences(node.hook or "")
    assert intro and deeper_says[0] != intro[0]

    # talk only: no duplicate materials persisted on deeper rungs
    assert after == before
    assert not any(e.type == "node.update" for e in deeper)
    assert deeper[-1].type == "done" and deeper[-1].data["nodes"] == 0


async def test_dive_cache_is_level_scoped(seeded, seams):
    """kid and expert hear different explanations — their dives cache apart."""
    from app.seams.companion.cache import MemoryDiveCache

    dive_cache = MemoryDiveCache()
    comp = make_companion(seams, plan=[], dive_cache=dive_cache)
    node = await seams.content.get_node_by_key("backpropagation")
    checkout = await _free_checkout(seams, "levels")

    _ = [e async for e in comp.explain_node(checkout.id, node.id, level="kid")]
    _ = [e async for e in comp.explain_node(checkout.id, node.id, level="expert")]
    assert len(dive_cache.store) == 2


async def test_dive_cache_keys_on_mastery_band(seeded, seams):
    """A learner with recorded confusion gets a 'shaky' dive — cached apart
    from the default one — while plain engagement stays in 'default' so a
    reopen still hits."""
    from app.ports import InteractionEvent
    from app.seams.companion.cache import MemoryDiveCache

    dive_cache = MemoryDiveCache()
    comp = make_companion(seams, plan=[], dive_cache=dive_cache)
    node = await seams.content.get_node_by_key("gradient-based-learning")
    if node is None:  # seed key differs across fixtures — fall back
        node = await seams.content.get_node_by_key("backpropagation")
    checkout = await _free_checkout(seams, "bands")

    _ = [e async for e in comp.explain_node(checkout.id, node.id)]
    assert all(":default:" in k for k in dive_cache.store)

    # reopen: the dive's own engagement must not have changed the band
    before = len(dive_cache.store)
    _ = [e async for e in comp.explain_node(checkout.id, node.id)]
    assert len(dive_cache.store) == before  # hit, not a new entry

    # explicit struggle -> shaky -> a differently-keyed, gentler dive
    for _i in range(2):
        await seams.learning.record(
            InteractionEvent(
                checkout_id=checkout.id,
                node_id=node.id,
                event_type="confused",
                payload={},
            )
        )
    await seams.learning.update_mastery(checkout.id, node.id)
    _ = [e async for e in comp.explain_node(checkout.id, node.id)]
    assert any(":shaky:" in k for k in dive_cache.store)


async def test_explain_derived_artifact_is_terminal(seeded, seams):
    """Opening a derived study artifact (Key points / Analogy) explains it in
    place but accretes no further cards — the recursion that produced
    'Key points: Analogy: …' must stop at the leaf."""
    comp = make_companion(seams, plan=[])
    concept = await seams.content.get_node_by_key("the-convolutional-network")
    checkout = await _free_checkout(seams, "deep dive")

    # Mining the concept produces the "Key points: …" artifact.
    _ = [e async for e in comp.explain_node(checkout.id, concept.id)]
    artifact = await seams.content.get_node_by_key(
        normalize_key(f"Key points: {concept.title}")
    )
    assert artifact is not None and artifact.kind == "artifact"

    # Opening that artifact streams an explanation but creates nothing new.
    before = await scalar("SELECT count(*) FROM canonical_nodes")
    events = [e async for e in comp.explain_node(checkout.id, artifact.id)]
    after = await scalar("SELECT count(*) FROM canonical_nodes")

    says = [e for e in events if e.type == "say"]
    assert len(says) >= 1 and all(
        e.data.get("node_id") == str(artifact.id) for e in says
    )
    assert after == before  # no "Key points: Key points: …" / "Analogy: Analogy: …"
    assert not any(e.type in ("node.update", "edge.create") for e in events)
    assert events[-1].type == "done" and events[-1].data["nodes"] == 0


async def test_pull_thread_does_not_compound_deeper_prefix(seeded, seams):
    """Pulling a thread off an 'A deeper look at …' node targets the underlying
    concept rather than stacking another prefix."""
    comp = make_companion(seams, plan=[])
    anchor = await seams.content.get_node_by_key("the-convolutional-network")
    checkout = await _free_checkout(seams, "rabbit hole")

    _ = [e async for e in comp.pull_thread(checkout.id, anchor.id)]
    deeper = await seams.content.get_node_by_key(
        normalize_key(f"A deeper look at {anchor.title}")
    )
    assert deeper is not None

    events = [e async for e in comp.pull_thread(checkout.id, deeper.id)]
    titles = [
        e.data["node"]["title"]
        for e in events
        if e.type in ("node.create", "node.update") and e.data.get("node")
    ]
    assert titles, "expected a node payload from the rabbit-hole branch"
    assert all("A deeper look at A deeper look at" not in t for t in titles)
    # it deepens the concept itself — which already exists, so it is reused
    assert any(t == f"A deeper look at {anchor.title}" for t in titles)


async def test_delivery_level_does_not_fork_the_corpus(seeded, seams):
    """Two learners viewing the same concept at different delivery levels share
    one canonical artifact — the level shapes ephemeral talk, never what persists."""
    comp = make_companion(seams, plan=[])
    node = await seams.content.get_node_by_key("the-convolutional-network")
    kid = await _free_checkout(seams, "kid")
    expert = await _free_checkout(seams, "expert")

    _ = [e async for e in comp.explain_node(kid.id, node.id, level="kid")]
    key = normalize_key(f"Key points: {node.title}")
    first = await seams.content.get_node_by_key(key)
    assert first is not None

    _ = [e async for e in comp.explain_node(expert.id, node.id, level="expert")]
    second = await seams.content.get_node_by_key(key)
    assert second is not None
    assert second.id == first.id  # reused, not forked
    assert second.body == first.body  # level-neutral canonical body


def test_core_title_unwinds_derived_prefixes():
    from app.seams.companion import _core_title

    assert _core_title("Analogy: Current AI Capabilities") == "Current AI Capabilities"
    assert _core_title("A deeper look at Analogy: X") == "X"
    assert _core_title("A deeper look at A deeper look at Key points: X") == "X"
    assert _core_title("The Convolutional Network") == "The Convolutional Network"


async def test_discuss_clarification_stays_ephemeral(seeded, seams):
    """A plain follow-up streams a spoken answer pinned to the card and records a
    `discussed` interaction, but accretes no new node (it was just a clarification)."""
    comp = make_companion(seams, plan=[])
    node = await seams.content.get_node_by_key("the-convolutional-network")
    checkout = await _free_checkout(seams, "discussion")

    before = await scalar("SELECT count(*) FROM canonical_nodes")
    events = [
        e async for e in comp.discuss(checkout.id, node.id, "Can you say that simpler?")
    ]
    after = await scalar("SELECT count(*) FROM canonical_nodes")

    # learner turn is echoed for replay; the answer streams as say events on the card
    assert any(e.type == "discuss" and e.data.get("role") == "learner" for e in events)
    says = [e for e in events if e.type == "say"]
    assert len(says) >= 2
    assert all(e.data.get("node_id") == str(node.id) for e in says)
    # a clarification creates nothing
    assert after == before
    assert not any(e.type in ("node.create", "node.update") for e in events)
    assert events[-1].type == "done"


async def test_discuss_new_concept_accretes_a_linked_card(seeded, seams):
    """A follow-up that surfaces a genuinely new concept canonicalizes into a new
    card linked back to the source by an `elaborates` edge (one thing leads to
    another), through the same chokepoint as every other generated node."""
    comp = make_companion(seams, plan=[])
    node = await seams.content.get_node_by_key("the-convolutional-network")
    checkout = await _free_checkout(seams, "discussion")

    new_title = "Synthetic discuss concept zeta"
    before = await scalar("SELECT count(*) FROM canonical_nodes")
    events = [e async for e in comp.discuss(checkout.id, node.id, f"NEW: {new_title}")]
    after = await scalar("SELECT count(*) FROM canonical_nodes")

    assert after > before
    assert any(e.type == "node.create" for e in events)
    assert any(e.type == "node.update" for e in events)  # gap -> canonicalize
    assert any(
        e.type == "edge.create" and e.data["edge"]["type"] == "elaborates"
        for e in events
    )
    # the new concept landed in the library, linked off the discussed card
    fresh = await seams.content.get_node_by_key(normalize_key(new_title))
    assert fresh is not None
    assert events[-1].type == "done"


async def test_enrich_emits_only_validated_media(seeded, seams, monkeypatch):
    """The visual layer: a neighbor mini-graph (from the canonical graph), a
    generated diagram (real Mermaid gate), and real web media — with every
    external reference resolved first, so dead/fabricated URLs are dropped."""
    from app.seams.companion import media_validation as mv

    async def yt(url, **_):
        return "GOOD" in url

    async def good_host(url, **_):
        return "good." in url

    monkeypatch.setattr(mv, "validate_youtube", yt)
    monkeypatch.setattr(mv, "validate_link", good_host)
    monkeypatch.setattr(mv, "validate_image", good_host)

    comp = make_companion(seams, plan=[])
    node = await seams.content.get_node_by_key("the-convolutional-network")
    checkout = await _free_checkout(seams, "visuals")

    events = [e async for e in comp.enrich(checkout.id, node.id)]
    media = [e for e in events if e.type == "media"]
    kinds = {e.data["media_kind"] for e in media}

    # neighbor mini-graph straight from the graph, with edges
    assert "graph" in kinds
    graph = next(e for e in media if e.data["media_kind"] == "graph")
    assert graph.data["graph"]["edges"]
    # generated diagram cleared the mermaid syntax gate
    assert "diagram" in kinds
    # only resolvable web media survived (the BAD/dead ones were dropped)
    assert [e.data["url"] for e in media if e.data["media_kind"] == "video"] == [
        "https://www.youtube.com/watch?v=GOODvid"
    ]
    assert [e.data["url"] for e in media if e.data["media_kind"] == "link"] == [
        "https://good.example/ref"
    ]
    assert [e.data["url"] for e in media if e.data["media_kind"] == "image"] == [
        "https://good.example/pic.png"
    ]
    # enrichment is a background side-channel: it streams media, never a turn
    # terminator (`done`) that would clear the shared busy flag.
    assert not any(e.type == "done" for e in events)


async def test_explain_node_strips_citation_markers(seeded, seams):
    from app.seams.companion import _flush_sentences, _sanitize

    # Citation markers go, and the whitespace they leave behind is normalized so
    # Piper doesn't pause oddly or read a stray symbol (garbled-audio cause).
    assert _sanitize("Backprop is the chain rule [W2] in disguise [L1].") == (
        "Backprop is the chain rule in disguise."
    )
    # Markdown links keep only their label; emphasis/code ticks and list/heading
    # leaders are stripped entirely.
    assert _sanitize("See [the paper](http://x.y) for **more** `detail`.") == (
        "See the paper for more detail."
    )
    assert _sanitize("# Heading\n- a bullet point") == "Heading a bullet point"
    remaining, sentences = _flush_sentences("One sentence. A second one. tail")
    assert sentences == ["One sentence.", "A second one."]
    assert remaining.strip() == "tail"


# ---------------------------------------------------------------------------
# Live-dialogue mining: the learner's own words accrete into the library
# ---------------------------------------------------------------------------


async def test_mine_session_distils_learner_dialogue(seeded, seams):
    """A session's learner/tutor turns get distilled into a grounded node through
    the canonicalize chokepoint, tagged with the session's provenance."""
    checkout = await _free_checkout(seams, "vector search")
    cid = checkout.id
    # Record the dialogue exactly as the WS durable log would: a learner `discuss`
    # turn plus the Tutor's `say` reply, each long enough to survive the min-span
    # coherence filter.
    await seams.library.record_event(
        cid,
        "discuss",
        {
            "node_id": str(uuid4()),
            "role": "learner",
            "text": "How does approximate nearest-neighbour search trade recall for "
            "speed inside a vector index when the dataset is large?",
        },
    )
    await seams.library.record_event(
        cid,
        "say",
        {
            "node_id": str(uuid4()),
            "text": "IVFFlat partitions vectors into lists and probes only a few, so "
            "raising the probe count buys recall at the cost of latency in a vector "
            "index — that is the recall/speed knob.",
        },
    )
    # A title unique to this test, so the session mine *creates* the node (and we
    # can assert its session provenance) rather than merging into one a sibling
    # miner test already left in the shared seeded DB.
    comp = _mining_companion(seams, lambda _u: "Live session ANN probe budget tradeoff")

    produced = await comp.mine_session(cid)

    assert produced >= 1
    node = await seams.content.get_node_by_key("live-session-ann-probe-budget-tradeoff")
    assert node is not None
    assert node.source_ref and node.source_ref.startswith(f"session-{cid}#")

    # Idempotent: nothing new on the next close — the watermark stops a re-mine.
    assert await comp.mine_session(cid) == 0


async def test_mine_session_skips_when_no_learner_words(seeded, seams):
    """A pure generation session (tutor `say` only, no learner turn) mines nothing
    — those nodes already canonicalized live — and advances the watermark."""
    checkout = await _free_checkout(seams, "no dialogue")
    cid = checkout.id
    await seams.library.record_event(
        cid,
        "say",
        {"text": "A tutor narration line with no learner turn anywhere in it."},
    )
    comp = _mining_companion(seams, lambda _u: "Should not be created")

    assert await comp.mine_session(cid) == 0
    assert await comp.mine_session(cid) == 0  # watermark advanced, still nothing
    assert await seams.content.get_node_by_key("should-not-be-created") is None

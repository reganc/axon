# Phase 2 — The Companion: agents, live generation, the Jarvis event stream

**Goal:** the system talks. A learner names a subject (or pulls a thread) and the companion
generates the graph live over a WebSocket, narrating as it builds, asking orienting
questions, accepting interruptions — while every generated node flows through Phase 1's
canonicalizer into the library. Plus the `learning` seam: mastery inferred from dialogue and
spaced-repetition scheduling.

**Runnable result:** open a checkout, say "teach me about Fourier transforms," and watch
nodes appear on a debug client while the companion speaks; interrupt mid-stream and it
adapts; the new nodes persist to the library and are reused on the next request.

---

## Scope

**In:** `companion` (LLM gateway + four agent roles + event-stream producer), `learning`
(mastery + scheduler), the WebSocket endpoint, Redis pub/sub fan-out, the Librarian worker.
**Out:** voice I/O polish and graph rendering (Phase 4 — P2 ships a minimal debug client only).

---

## LLM gateway (port `LLMPort`)

```python
class LLMPort(Protocol):
    async def stream(self, msgs: list[Msg], tier: Literal["fast","reason"]) -> AsyncIterator[Delta]: ...
    async def complete(self, msgs: list[Msg], tier: str) -> str: ...
    async def embed(self, text: str) -> list[float]: ...   # 768-dim, Ollama nomic-embed-text
```

Routing: `tier="fast"` → Ollama (narration, quick adaptations, recall phrasing);
`tier="reason"` → Anthropic API (spine planning, canonicalization judgment, grounding).
Model names, base URLs, and the tier→model map all via config.

## Agent roles (all in `companion`, sharing the same tools)

Tools available to agents: `LibraryPort` (search/coverage/get_subgraph/write via canonicalize),
`LLMPort`, and a `SourceFetchPort` (web/url fetch — used by Researcher).

- **Planner** (`tier=reason`): subject → plan. Calls `library.coverage`, decides which nodes
  exist (reuse), which are gaps (generate), and the spine order. Emits a build plan the Tutor executes.
- **Tutor** (`tier=fast`, the in-session loop): drives the event stream. Per step: emit `say`
  narration, optionally `ask` an orienting question, request generation of the next gap node,
  decide when to offer a `rabbit_hole` or inject a `recall` prompt. Holds and updates
  `checkout.companion_memory`.
- **Researcher** (`tier=reason`): for every **generated** node, ground it — fetch/verify
  against sources, attach citations to `source_ref`, set `confidence`. Nodes failing a
  confidence floor are flagged, not published as fact. (Skip for `authored`/`locked` nodes.)
- **Librarian** (background worker, no learner present): periodic curation — merge
  near-duplicates the live path created, refine nodes with high `confusion_count`, promote
  high-traffic edge paths into emergent spines, decay stale edge weights.

## The event stream (the "Jarvis" mechanism)

One typed stream the Tutor produces; the frontend demuxes it into voice + canvas.

**Transport:** `WS /ws/companion/{checkout_id}` (JWT in the connect handshake). Server also
publishes each event to Redis channel `axon:checkout:{id}` for multi-device fan-out.

**Server → client events:**

| type | payload | rendered as |
|------|---------|-------------|
| `say` | `{text}` | narration → voice/chat |
| `ask` | `{prompt, options?}` | a question to the learner; stream pauses for input |
| `node.create` | `{temp_id, node}` | node appears on canvas (optimistic) |
| `node.update` | `{temp_id, canonical_id, patch}` | reconcile after canonicalize |
| `edge.create` | `{edge}` | edge drawn |
| `status` | `{phase, detail}` | "checking the library…" |
| `done` | `{}` | turn complete |

**Client → server events:** `answer{text}`, `interrupt{text}` (barge-in — re-enters the
Tutor loop mid-build), `pull_thread{node_id}` (spawn a rabbit-hole branch).

**Optimistic → canonical reconciliation:** the Tutor emits `node.create` with a `temp_id`
immediately (instant render in the learner's overlay), then the candidate goes through
`IngestionPort.canonicalize`; the resulting canonical id comes back as `node.update`. So
generation feels instant while the library stays the source of truth. **Talk is the
experience layer; the Phase-1 loop is still the source of truth.**

## Seam: `learning` (port `LearningPort`)

```python
class LearningPort(Protocol):
    async def record(self, event: InteractionEvent) -> None: ...   # → interaction_events hypertable
    async def update_mastery(self, checkout_id: UUID, node_id: UUID) -> float: ...
    async def due_reviews(self, checkout_id: UUID) -> list[UUID]: ...   # spaced repetition
```

Mastery is a fuzzy 0..1 signal inferred from events (`explained_back`, `recall_attempt`
results, `confused`), not a quiz score. Scheduler uses a standard spaced-repetition curve
(SM-2-style is fine) writing `next_review_at`. Due reviews surface as Tutor `ask` events in
later sessions — never as a blocking test.

---

## Acceptance criteria

- [ ] Connecting to `/ws/companion/{id}` with a valid JWT and sending a subject yields a
      stream of `say` + `node.create` + `edge.create` ending in `done`.
- [ ] Requesting a subject already in the library (e.g. "convolutional networks") **reuses**
      existing nodes (Planner coverage hit) and generates few/no new ones.
- [ ] Every generated node lands in the library via canonicalize (verify it's queryable
      afterward) with `origin in (ai_generated, ai_extended)` and a `confidence` set by Researcher.
- [ ] A near-duplicate of an existing concept merges rather than duplicating.
- [ ] An `interrupt` mid-stream visibly changes the next events.
- [ ] Generated nodes never overwrite a `locked` authored node (verify against the seed).
- [ ] `learning.record` writes to the hypertable; `update_mastery` moves with `explained_back`
      events; `due_reviews` returns nodes once `next_review_at` passes.
- [ ] Librarian worker run merges two deliberately-seeded near-duplicate AI nodes into one.

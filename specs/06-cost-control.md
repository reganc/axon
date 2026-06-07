# Cost Control & LLM Routing (cross-cutting)

**Applies to:** the companion LLM gateway (Phase 2), ingestion (Phases 1 & 3), and the
`learning` seam (budgets). Not a numbered phase — a policy every LLM-touching seam follows.

**Goal:** keep Anthropic API spend bounded and *amortizing* without compromising the
curiosity-graph experience. The system should make runaway spend structurally impossible,
not merely unlikely.

> **Pricing note (verify before relying on numbers).** Figures below are representative as of
> mid-2026 from the Claude pricing page; confirm current rates at
> `https://platform.claude.com/docs/en/about-claude/pricing`. The *policy* is rate-independent;
> only the constants move.

---

## 0. Principle — the library is a cache

Every canonicalized node is permanent, shared, reused-by-everyone content. Generation cost is
**front-loaded and decays**: the Nth learner on a topic pays ~zero. So the objective is
**maximize reuse hit-rate**, not minimize generation. This is why mass pre-generation was
rejected (full price for un-requested, low-reuse content) and why anchors matter (they channel
learners onto *shared* subgraphs). Treat the canonicalizer's `action=merged` rate as a core
cost KPI.

---

## 1. Tiered routing — the master lever

Routing has three axes: **local vs cloud**, and within cloud, **which model**. The 3060 runs
Ollama (~8B-class) at $0 API; reserve Claude for where quality pays back. Representative cloud
rates: Haiku 4.5 ≈ $1/$5, Sonnet 4.6 ≈ $3/$15, Opus ≈ $5/$25 per Mtok (in/out).

| Task | Tier | Model | Why |
|------|------|-------|-----|
| Companion narration (`say`) | local | Ollama chat | high volume, latency-critical, $0 |
| Orienting questions (`ask`) phrasing | local | Ollama chat | volume |
| Retrieval-practice phrasing | local | Ollama chat | volume |
| Embeddings (canonicalization, search) | local | `nomic-embed-text` | $0, fast |
| Transcript topic extraction (P3) | cloud-batch | Haiku 4.5 | bulk, simple, latency-tolerant |
| Node **draft** generation (hook + body) | local | Ollama chat | draft first; escalate only on need |
| Spine planning (Planner) | cloud | Sonnet 4.6 | reasoning quality pays back |
| Canonicalization merge — **gray band only** | cloud | Sonnet 4.6 | clear cases decided by threshold, **no LLM call** |
| Grounding / verification (Researcher) | cloud-batch where possible | Sonnet 4.6 | accuracy-critical |
| Librarian refinement / merges | cloud-batch | Haiku/Sonnet | off-peak, async |
| Cheap cloud classification/routing | cloud | Haiku 4.5 | 3× cheaper than Sonnet |

**Escalation policy (local-first):** generate a local draft; escalate to Sonnet only when the
draft fails a quality bar — `confidence < AXON_ESCALATE_FLOOR` (default 0.6), or the node is an
`authored`/anchor candidate (locked content earns Claude quality once). Never escalate
narration. Opus is not in the default path; use only for a task that demonstrably needs it.

**No-LLM fast paths:** canonicalization decides by embedding similarity alone outside a gray
band (`< related_threshold` → create; `≥ merge_threshold` → merge). Only the band between them
costs a reasoning call. Most merges should be free.

---

## 2. Prompt caching (≈90% off repeated input)

Cache reads cost ~10% of standard input; a 5-min cache write costs ~1.25× (1-hour ≈ 2×). Pays
back after the first read.

- Structure every cloud prompt as **`[stable cached prefix] + [volatile suffix]`**. Mark the
  prefix with `cache_control: {type: "ephemeral"}`.
- Cache the companion **persona/system prompt + tool definitions** (1-hour TTL — shared across
  all concurrent sessions). Cache the **current subgraph context block** per turn (5-min TTL).
- Constraints: minimum 1024 tokens to cache; **exact-match** prefix — keep the cached region
  byte-stable (no per-call timestamps/ids inside it).
- This compounds with §4: the graph lets you send a *small* context, and cache the stable part of it.

---

## 3. Batch API (50% off, async ≤24h)

For any latency-tolerant workload, submit via the Message Batches API — 50% off input *and*
output, stacks with caching toward ~5% of standard cost.

- **Use it for:** the transcript miner (P3 — the single biggest one-time sink), one-time
  baseline generation (§6), nightly Librarian curation, and re-grounding sweeps.
- **Never batch** the live companion or anything in a learner's interactive loop.

---

## 4. Context minimization

- Send only the precise neighborhood: current node + 1-hop edges + a short learner-state
  summary — not the whole subgraph. The graph makes this exact; don't degrade to stuff-everything RAG.
- Lean, structured prompts (shorter inputs *and* shorter outputs).
- Default to **global routing**; the US-only region carries a ~1.1× multiplier — only opt in if
  data residency requires it.

---

## 5. Grounding economics

Ground **once**: only `new`/low-confidence nodes, never `locked`/authored, never re-ground a
canonized fact. Cache verification results per `source_ref`. Batch grounding (§3). Ground at the
claim level where feasible so a flagged claim doesn't re-cost the whole node.

---

## 6. The authored baseline — deep, narrow, once, locked

The cost-optimal baseline is the opposite of broad: pick the **3–5 highest-traffic domains** for
your pilot audience and build a *dense, well-connected* baseline there. Generate it **one time
through the Batch API (+ caching)** at ~50% off, then `lock` it as `authored` anchors →
permanent zero-cost reuse in exactly the areas that get hit most. Pair with the Phase 5
Question/Person anchors, which raise hit-rate by funnelling learners onto shared subgraphs.
Breadth spreads paid generation across cold topics; depth maximizes reuse. **Do not** revive
broad mass-generation.

---

## 7. Budget meter + circuit breaker (the safety net)

Make overspend impossible, not unlikely. Wrap `LLMPort` with a metering+budget layer.

```python
TaskKind = Literal[
    "narration","ask","recall","embed","extract","draft","hook",
    "plan","merge_judgment","ground","curate","classify",
]

class Routed(BaseModel):
    tier: Literal["local","cloud"]
    model: str | None      # cloud model id, or None for local
    batch: bool = False

class RoutingPolicy(Protocol):
    def route(self, task: TaskKind, *, confidence: float | None = None) -> Routed: ...

class UsageMeter(Protocol):
    async def record(self, *, task: TaskKind, role: str, tier: str, model: str | None,
                     input_tokens: int, cached_input_tokens: int, output_tokens: int,
                     checkout_id: UUID | None, user_id: UUID | None) -> None: ...

class BudgetGate(Protocol):
    async def allow(self, *, user_id: UUID | None, est_cost: float) -> bool: ...
    async def spent(self, window: Literal["session","day","global"], user_id: UUID | None) -> float: ...
```

- **Meter** every cloud call: input/output tokens, **cached vs fresh** split, tier, model,
  agent role, checkout/user. Persist to `interaction_events` (and surface to comet-observer).
- **Budgets** (config): per-session, per-user-per-day, and a global daily ceiling.
- **Circuit breaker:** when a window crosses its soft threshold, **degrade to local-only** —
  narration and local draft generation keep working; planning/grounding are *queued for the
  nightly batch*; the UI shows a gentle "depth mode paused" state, not an error. At the global
  hard ceiling, all cloud calls stop until reset.
- The breaker degrades the *economics*, never the basic experience: a learner can always read,
  traverse, and talk to the companion.

---

## Config additions (env, `AXON_` prefix)

```
AXON_MODEL_REASON=claude-sonnet-4-6     # default cloud reasoning model
AXON_MODEL_CHEAP=claude-haiku-4-5       # cheap cloud tasks
AXON_ESCALATE_FLOOR=0.6                 # local->cloud draft escalation bar
AXON_CACHE_TTL_PERSONA=1h
AXON_CACHE_TTL_CONTEXT=5m
AXON_BATCH_ENABLED=true
AXON_BUDGET_SESSION_USD=0.50
AXON_BUDGET_USER_DAILY_USD=2.00
AXON_BUDGET_GLOBAL_DAILY_USD=50.00
```

## Acceptance criteria

- [ ] Routing implemented; the meter shows narration, embeddings, and transcript extraction
      **never** hit Claude.
- [ ] Companion cloud calls carry a cached prefix; after the first turn, `cache_read_input_tokens > 0`.
- [ ] Transcript miner and baseline generation run through the Batch API (visible as batch line items).
- [ ] No live/interactive companion call is ever batched.
- [ ] Canonicalization makes **no** LLM call outside the gray band (verify on clear create/merge cases).
- [ ] Meter records every cloud call tagged by task/role/tier/model with cached-vs-fresh tokens.
- [ ] Simulated over-budget → system degrades to local-only: companion still narrates,
      grounding/planning queue for batch, UI shows "depth mode paused".
- [ ] Grounding skips `locked` nodes and never re-grounds a canonized fact.

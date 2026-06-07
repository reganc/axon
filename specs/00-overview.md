# AXON — Implementation Handoff (Overview)

> **Codename:** AXON (placeholder — find-replace to rename).
> **What it is:** a curiosity-graph LMS. Instead of *courses and tests*, learners
> traverse a knowledge graph: an authored or AI-generated **spine** threads through
> a wider **web** of concept nodes, with an always-present **AI companion** that
> generates content live, narrates as it builds, and infers mastery from dialogue
> rather than gating with quizzes. The library is **self-augmenting**: everything the
> system generates or a learner interacts with accretes back into a shared graph.

This document orients the build. Each phase has its own spec in `specs/`. The data
layer is already designed and seeded — see `artifacts/`.

---

## 1. Core model (one paragraph)

The atom is a **concept node** (`hook → body → recall`), not a lesson. Nodes connect
via typed **edges** (`prerequisite`, `elaborates`, `applies`, `contrasts`, `rabbit_hole`,
`next_in_spine`). A **spine** is an ordered path through the web. The **canonical graph**
is global and shared (the library that grows); a **checkout** instantiates a per-learner
**overlay** (progress, notes, the companion's memory of that learner). Live generation
flows through one loop: *request → library lookup (reuse) → generate only the gaps →
canonicalize & persist (dedup/version/provenance) → learner overlay → interactions accrete
→ richer library next time.*

---

## 2. Architecture — modular monolith with seams

Same pattern as ledgerworks. One FastAPI backend, one Next.js frontend. Internally the
backend is split into **seams**; seams depend on each other only through **ports**
(Python `Protocol`/ABC interfaces in `app/ports.py`), never on concrete implementations.

| Seam | Responsibility | Key port | Reuse |
|------|----------------|----------|-------|
| `identity` | JWT auth, RBAC (`learner`/`author`/`admin`) | `AuthPort` | lift from carecore/havencore |
| `content` | canonical graph CRUD: nodes, edges, spines, sources | `ContentPort` | — |
| `library` | semantic search, spine assembly, checkout/overlay | `LibraryPort` | — |
| `learning` | mastery model, spaced-repetition scheduler | `LearningPort` | — |
| `companion` | agent roles, LLM gateway, event-stream producer | `CompanionPort`, `LLMPort` | — |
| `ingestion` | source ingestion + canonicalization (markdown loader, transcript miner) | `IngestionPort` | — |

The **canonicalize-and-persist** routine lives in `ingestion` and is called by both the
seed loader (Phase 1) and the companion's live generation (Phase 2) — it is the single
chokepoint that guarantees the library never duplicates or forgets.

```
Phase 1  identity + content + library + ingestion(seed loader) + canonicalization
Phase 2  companion (agents, LLM gateway, WebSocket event stream) + learning
Phase 3  ingestion(transcript miner) for Claude Code / Obsidian history
Phase 4  Next.js frontend (graph canvas, companion panel, library, theming)
```

Build in order; each phase is runnable on its own.

---

## 3. Stack & conventions

- **Backend:** FastAPI (async), SQLAlchemy 2.x + asyncpg.
- **DB:** PostgreSQL 15 + `pgvector` (canonicalization, related-concept search) +
  TimescaleDB (the `interaction_events` hypertable).
- **Cache/transport:** Redis — sessions, rate limiting, and **pub/sub for the companion
  event stream** (channel per checkout, enables multi-device).
- **Inference:** an `LLMPort` gateway abstracting **Ollama** (local, RTX 3060 — fast
  conversational turns, embeddings via `nomic-embed-text`, 768-dim) and the **Anthropic
  API** (Planner reasoning, Researcher verification). Route by task tier.
- **Frontend:** Next.js (App Router), Tailwind, light/dark.
- **Packaging:** Docker Compose, one service per concern. Slot into comet conventions:
  - suggested ports — API+WS `8100`, frontend `8101` (prod), Postgres/Redis internal only.
  - suggested subnet — `172.31.0.0/24` (confirm next-free against your existing 172.28/172.30).
  - apps root — `~/apps/axon/`.

---

## 4. Repo layout

```
axon/
  docker-compose.yml
  .env.example
  artifacts/                     # this handoff's artifacts (see §5)
  backend/
    app/
      main.py                    # FastAPI app, router + WS mounts, lifespan
      config.py                  # pydantic-settings; all knobs via env
      db.py                      # async engine, session, pgvector registration
      ports.py                   # ALL seam contracts (Protocol/ABC) — the seams
      seams/
        identity/  content/  library/  learning/  companion/  ingestion/
      api/
        routers/                 # one HTTP router per seam
        ws/companion.py          # WebSocket event-stream endpoint
    workers/librarian.py         # background curator (APScheduler/Celery)
    migrations/                  # alembic; baseline = artifacts/schema.sql
    tests/
  frontend/                      # Next.js (Phase 4)
```

**Rule for the implementer:** define every cross-seam call in `ports.py` first, then
implement behind it. A seam may import another seam's *port*, never its module internals.

---

## 5. Artifact manifest (`artifacts/`)

| File | What it is | Used by |
|------|-----------|---------|
| `schema.sql` | Postgres DDL for the full data model (graph + overlay + events). pgvector + TimescaleDB. | Phase 1 — alembic baseline |
| `lecun_seed_graph.json` | The first course atomized: 30 nodes, 41 edges, 3 spines, 1 source. All `origin: authored`, `locked: true`. | Phase 1 — seed loader fixture & test data |
| `build_lecun_seed.py` | Deterministic builder (uuid5 keys) that produced the JSON. Documents the atomization logic; re-runnable. | reference; regenerate seed if format changes |

The seed is the **acceptance fixture** for Phase 1: after loading, the graph queries,
search, and checkout must all work against it.

---

## 6. Cross-cutting requirements

- **Config:** everything via env (`config.py`). No hardcoded secrets, ports, or model names.
- **Provenance is mandatory:** every node carries `origin`, `source_ref`, `confidence`.
  Authored nodes are `locked`; the canonicalizer **augments around them, never overwrites**.
- **Accuracy > coverage:** generated educational content must be grounded (Phase 2
  Researcher) and surface uncertainty rather than smoothing it. A confidently wrong node
  is the worst failure mode in an LMS.
- **No tests-as-gates anywhere.** `recall_prompts` schedule retrieval; they never block.
- **Tests:** each seam ships unit tests against its port; Phase 1 ships an integration
  test that loads the seed and exercises search + checkout.

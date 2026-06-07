# Phase 1 — Foundation: graph, identity, library, canonicalization

**Goal:** a running backend with the full data model, JWT/RBAC, the LeCun seed loaded,
semantic search over the library, checkout/overlay, and the canonicalize-and-persist
routine that every later phase depends on. No AI generation yet — this phase proves the
*storage and reuse* substrate.

**Runnable result:** `docker compose up` brings up Postgres+pgvector+Timescale, Redis,
and the API. A script loads `lecun_seed_graph.json`. An author can browse the graph; a
learner can check out a spine and walk it.

---

## Scope

**In:** `identity`, `content`, `library`, `ingestion` (seed loader + canonicalization core),
DB migrations, Docker Compose, seed integration test.
**Out:** companion/agents (Phase 2), transcript miner (Phase 3), frontend (Phase 4).

---

## Data layer

- Baseline migration = `artifacts/schema.sql` (review it; it is authoritative for columns).
- Register `pgvector` in `db.py`; embedding dim **768** (`nomic-embed-text`).
- Enable TimescaleDB and `create_hypertable('interaction_events','ts')` (no-op writes ok in P1).

## Seam: `identity` (port `AuthPort`)

Lift JWT + RBAC from carecore/havencore. Roles: `learner`, `author`, `admin`.

```python
class AuthPort(Protocol):
    def issue_token(self, user_id: UUID, role: str) -> str: ...
    def verify(self, token: str) -> Principal: ...        # raises on invalid/expired
    def require(self, principal: Principal, perm: str) -> None: ...  # RBAC check
```

Permissions (minimum): `graph:read`, `graph:write` (author/admin), `node:lock` (author/admin),
`checkout:create`, `checkout:read:self`.

## Seam: `content` (port `ContentPort`)

CRUD over `canonical_nodes`, `edges`, `spines`, `sources`. Enforce: **a `locked` node may
not be updated via normal CRUD** (only the canonicalizer may, and only by adding edges /
neighbor nodes — never overwriting body/hook).

```python
class ContentPort(Protocol):
    async def upsert_node(self, node: NodeIn) -> Node: ...
    async def add_edge(self, src: UUID, dst: UUID, type: str, origin: str, weight: float = 1.0) -> Edge: ...
    async def get_subgraph(self, node_ids: list[UUID], depth: int = 1) -> Subgraph: ...
    async def get_spine(self, spine_id: UUID) -> SpineWithNodes: ...
```

## Seam: `library` (port `LibraryPort`)

Semantic search + spine assembly + checkout.

```python
class LibraryPort(Protocol):
    async def search(self, query: str, k: int = 10) -> list[ScoredNode]: ...     # pgvector cosine
    async def coverage(self, subject: str) -> Coverage: ...                       # what exists vs gaps
    async def checkout(self, user_id: UUID, spine_id: UUID | None, subject: str | None) -> Checkout: ...
    async def overlay_state(self, checkout_id: UUID) -> list[NodeState]: ...
```

`checkout()` creates a `checkouts` row and lazily materializes `node_states` (mastery 0)
for the spine's nodes. Free-roam checkout (`spine_id=None`) is allowed.

## Seam: `ingestion` — canonicalization core (port `IngestionPort`)

This is the single most important routine in the system. It must be deterministic and
idempotent so re-ingesting never duplicates.

```python
class IngestionPort(Protocol):
    async def canonicalize(self, candidate: CandidateNode) -> CanonResult: ...
    async def ingest_seed(self, path: str) -> IngestReport: ...   # loads lecun_seed_graph.json
```

**`canonicalize(candidate)` algorithm:**

1. `key = normalize(candidate.title or candidate.key)` → slug.
2. `emb = LLMPort.embed(candidate.hook + candidate.body)`  *(P1 may stub via direct Ollama call)*.
3. Nearest neighbor in `canonical_nodes` by cosine similarity `s`.
4. Decision:
   - `s ≥ 0.92` **or** exact key match → **MERGE**. If the match is `locked` → do **not**
     modify it; instead attach a lateral edge from the candidate's context and return the
     existing node. If unlocked → `version += 1`, append provenance, set `origin='ai_extended'`.
   - `0.80 ≤ s < 0.92` → **CREATE** new node, add `elaborates`/`related` edge to the neighbor.
   - `s < 0.80` → **CREATE** standalone new node.
5. Return `CanonResult{node, action: merged|created, neighbor?}`.

Thresholds in config. The **seed loader** bypasses the merge step for authored nodes
(they are inserted verbatim with `locked=true`) but still computes embeddings.

---

## API (FastAPI routers)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/auth/token` | — | issue JWT (dev: seed users) |
| GET | `/graph/nodes/{id}` | `graph:read` | node + immediate edges |
| GET | `/graph/spines/{id}` | `graph:read` | spine with ordered nodes |
| GET | `/library/search?q=` | `graph:read` | semantic search |
| POST | `/library/checkout` | `checkout:create` | start a learning space |
| GET | `/library/checkout/{id}` | `checkout:read:self` | overlay state |
| POST | `/ingest/seed` | `graph:write` | load the seed JSON (idempotent) |

---

## Acceptance criteria

- [ ] `docker compose up` healthy; `/ingest/seed` loads `lecun_seed_graph.json` →
      **30 nodes, 41 edges, 3 spines**; running it twice changes nothing (idempotent).
- [ ] All seeded nodes have non-null 768-dim embeddings after load.
- [ ] `GET /library/search?q=convolution` returns the CNN cluster ranked sensibly.
- [ ] `GET /graph/spines/{foundations}` returns the 10 foundation nodes in order.
- [ ] Checking out the Foundations spine creates 10 `node_states` at mastery 0.
- [ ] Attempting to overwrite a `locked` node via `content` CRUD is rejected.
- [ ] `canonicalize()` on a near-duplicate of `cnn-weight-sharing` returns `action=merged`
      against the existing node and does **not** create a second node.
- [ ] RBAC: a `learner` token is denied `graph:write`.

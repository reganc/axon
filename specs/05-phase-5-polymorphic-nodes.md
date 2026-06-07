# Phase 5 — Polymorphic node typology + cold-start anchors

**Status of the project:** Phases 1–4 are complete and running (graph + RBAC, the
companion event stream, the transcript miner, the frontend). This is an **additive change**
on the live system, not a greenfield phase. It must be backward-compatible with the data
already loaded (the 30-node LeCun seed and anything generated since).

**Goal:** make node *type* a first-class concept. Today a node is `kind ∈ {concept, apply}`.
This phase generalizes it to `{concept, apply, question, person, artifact, project, skill}`,
adds a few relationship types, seeds a small set of curiosity **anchors** for cold-start, and
re-expresses the LeCun pilot as a **Person-anchored subgraph**. It also adds a derived,
optional taxonomy *view* — without making a hand-authored taxonomy the substrate.

> **Context for this change (read before implementing).** This came out of evaluating an
> external proposal to pre-seed a 10,000–50,000-node subject taxonomy. We adopted the part
> that fits AXON (richer node/edge types, cold-start anchors) and **rejected** the part that
> doesn't (mass pre-generation). See "Explicitly out of scope" below — that rejection is a
> design decision, not an omission.

---

## 1. Node types (extend `kind`)

`canonical_nodes.kind` is already a `TEXT` column, so **no enum DDL is needed** — the new
values are valid immediately. Validation lives in the application layer.

| kind | what it is | body? | role in the graph |
|------|-----------|-------|-------------------|
| `concept` | an idea (existing) | yes (`hook → body → recall`) | the workhorse |
| `apply` | a build/do task (existing) | uses `apply_prompt` | constructionism |
| `question` | a curiosity gap as an object ("Why do black holes evaporate?") | **no answer body** — `hook` frames why it's interesting | a **generation seed**: opening it asks the companion to build an answer-subgraph |
| `person` | a thinker/creator hub ("Yann LeCun") | short bio in `body` | a hub other nodes point at |
| `artifact` | a book / paper / video / dataset | citation + summary | a groundable external reference |
| `project` | a larger build ("Build a neural network") | brief + deliverable | richer target for `apply`-style work |
| `skill` | a cross-cutting ability ("first-principles thinking") | short | connected across subjects via edges, **never** siloed in its own domain |

Type-specific data goes in a new `attributes JSONB` column (not new sparse columns).
Suggested shapes (free-form, documented, not rigidly enforced):

- `person`: `{born, died?, country, affiliations[], notable_for[], links[]}`
- `artifact`: `{artifact_kind: paper|book|video|dataset, year, url, doi?}`
- `question`: `{status: open|being_explored, difficulty}`
- `project`: `{difficulty, deliverable, est_hours}`
- `skill`: `{kind: cognitive|method|tool}`

## 2. Relationship types (extend `edges.type`)

Also `TEXT` — additive, no DDL. Add to the existing set
(`next_in_spine`, `prerequisite`, `elaborates`, `applies`, `contrasts`, `rabbit_hole`):

- `authored_by` — artifact/concept → person
- `about` — concept/spine → person or question
- `answers` — concept → question
- `inspired_by` — node → node (intellectual lineage)
- `contradicts` — node → node (logical opposition; distinct from `contrasts`, which is a teaching device)
- `teaches` — skill → concept

## 3. Code changes — `backend/app/ports.py`

Widen two Literals and add one field. Routers/seams that depend only on the port types
keep working.

```python
NodeKind = Literal["concept", "apply", "question", "person", "artifact", "project", "skill"]
EdgeType = Literal[
    "next_in_spine", "prerequisite", "elaborates", "applies", "contrasts", "rabbit_hole",
    "authored_by", "about", "answers", "inspired_by", "contradicts", "teaches",
]

class NodeIn(BaseModel):
    # ...existing fields...
    attributes: dict = Field(default_factory=dict)   # NEW: type-specific data
```

## 4. Migration (live DB)

One DDL change plus a kind index for type-filtered queries. New alembic revision:

```sql
ALTER TABLE canonical_nodes ADD COLUMN attributes JSONB NOT NULL DEFAULT '{}';
CREATE INDEX IF NOT EXISTS idx_nodes_kind ON canonical_nodes (kind);
-- optional guardrail (kept loose so generation isn't blocked):
-- ALTER TABLE canonical_nodes ADD CONSTRAINT chk_kind CHECK (kind IN
--   ('concept','apply','question','person','artifact','project','skill'));
```

Existing rows get `attributes = '{}'` and keep their `kind`; nothing else moves. Apply
`artifacts/schema.sql` updates to match for fresh installs.

## 5. Seam impacts

- **`content`** — accept the new kinds/edge types; serialize `attributes`.
- **`library`** — `search`/`coverage` become type-aware (optional `kinds` filter); add an
  **entry-points** query that surfaces `question` and `person` anchors for a cold-start home screen.
- **`companion` (Phase 2 behavior)** — a `question` node is a **generation seed**: when a
  learner opens or checks out a question with no answer-subgraph yet, the Planner generates
  the concepts that `answers` it rather than serving a body. Person nodes can anchor a
  generated subgraph. **Researcher grounding is mandatory for `person` and `artifact`
  factual attributes** (dates, affiliations, citations) — these are exactly the facts a
  learner can't catch if wrong.
- **`frontend` (Phase 4)** — render node types distinctly on the canvas (a person hub, a
  question marker, an artifact card) and let `about`/`authored_by` edges be navigable.

## 6. Cold-start anchors (the part that replaces mass-seeding)

Create one new authored source, `artifacts/anchor_seed.json`, in the **same format the
existing seed loader already ingests** (`IngestionPort.ingest_seed`). Contents:

- a curated set of `question` anchors (the "great questions" — consciousness, intelligence,
  origin of life, etc.) with strong hooks and **no answer bodies**;
- a curated set of `person` anchors (key thinkers) with grounded `attributes`;
- optionally a few `project` anchors.

All `origin: authored`, `locked: true`. **Target hundreds of anchors, not thousands** — these
are evocative entry points that *seed generation*, not content. Load with the existing
idempotent loader; re-running changes nothing.

## 7. Re-anchor the LeCun pilot

Demonstrate Person-as-hub on real data. Add to `build_lecun_seed.py` (then re-run
`ingest_seed` — idempotent uuid5 keys mean only the new rows are added):

- a `person` node `person-yann-lecun` with grounded `attributes`
  (`{born: 1960, country: France, affiliations: [Bell Labs, NYU, Meta], notable_for: [CNNs, ...]}`);
- `about` edges from the three spine signature nodes (`the-convolutional-network`, `jepa`,
  `lecuns-connectionist-bet`) → `person-yann-lecun`;
- keep the three spines as-is; they now read as one Person-anchored subgraph.

## 8. Taxonomy as a *view*, not the substrate

If a browse hierarchy is wanted, derive it **lazily from whatever the graph actually
contains** — cluster/tag nodes by embedding + LLM labels, cache the result, expose it as a
read-only `/browse/facets` lens. Do **not** store a hand-fixed Domain→Subject→Topic tree as
the source of truth; structure should emerge from traffic (the existing emergent-spine
mechanism). Hierarchy is one way to look at the graph, not what the graph is.

---

## Explicitly out of scope (rejected by design)

- **Mass pre-generation of a 10k–50k subject taxonomy.** It inverts the self-augmenting
  model, produces definition-first husks with no learner context, violates accuracy-over-coverage
  (tens of thousands of ungrounded low-confidence nodes), and poisons canonicalization (real
  generated nodes would have to dedup against stubs). Cold-start is solved by anchors (§6), not volume.
- Hand-authored hierarchical taxonomy as substrate (§8 makes it a derived view instead).

## Acceptance criteria

- [ ] Migration applies to the live DB; the existing 30 LeCun nodes are unchanged and now
      carry `attributes = {}`.
- [ ] `content` CRUD and the API accept all seven node kinds and the new edge types.
- [ ] `anchor_seed.json` loads via the existing seed loader; re-running is idempotent.
- [ ] `person-yann-lecun` exists; the three `about` edges resolve; querying the person returns
      its subgraph (the three spines hang off it).
- [ ] Opening a `question` anchor with no answer-subgraph triggers the companion to **generate**
      concepts linked by `answers` edges — not serve a canned body.
- [ ] `person`/`artifact` factual attributes pass Researcher grounding; ungrounded facts are
      flagged, not published.
- [ ] `/browse/facets` returns a hierarchy derived from current graph contents; adding nodes
      changes it (proving it's a view, not a stored tree).
- [ ] No mass-generated taxonomy nodes exist; anchor count is in the hundreds.

-- ============================================================================
--  LMS — canonical knowledge graph + learner overlay
--  Postgres 15+ with pgvector + (optional) TimescaleDB
--  This is the storage layer the spine/web/companion model runs on.
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
-- CREATE EXTENSION IF NOT EXISTS timescaledb;   -- enable on comet for the event stream

-- ----------------------------------------------------------------------------
--  SOURCES — authored artifacts kept as immutable source-of-record.
--  Every node carries provenance back to one of these so nothing is ever lost.
--  kind: 'markdown_course' | 'claude_code_transcript' | 'obsidian_note' | 'url' | 'pdf'
-- ----------------------------------------------------------------------------
CREATE TABLE sources (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    kind         TEXT NOT NULL,
    title        TEXT NOT NULL,
    uri          TEXT,                 -- file path / URL on disk
    raw_content  TEXT,                 -- optional inlined copy
    ingested_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ----------------------------------------------------------------------------
--  CANONICAL_NODE — the atom. Global, shared, self-augmenting library.
--  origin: 'authored' (locked anchor) | 'ai_generated' | 'ai_extended'
--  kind:   'concept' | 'apply'
-- ----------------------------------------------------------------------------
CREATE TABLE canonical_nodes (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    canonical_key    TEXT UNIQUE NOT NULL,        -- normalized key for dedup
    title            TEXT NOT NULL,
    kind             TEXT NOT NULL DEFAULT 'concept',
    hook             TEXT,                        -- curiosity-gap opener
    body             TEXT,                        -- core explanation (markdown)
    apply_prompt     TEXT,                        -- for kind='apply' (constructionism)
    recall_prompts   JSONB NOT NULL DEFAULT '[]', -- spaced-retrieval, NOT gates
    mastery_criteria JSONB NOT NULL DEFAULT '[]',
    depth_level      TEXT,                        -- 'intro' | 'core' | 'apply'
    embedding        VECTOR(768),                 -- nomic-embed-text on Ollama; canonicalization + related edges
    origin           TEXT NOT NULL DEFAULT 'ai_generated',
    locked           BOOLEAN NOT NULL DEFAULT FALSE,  -- authored anchors: AI extends around, never overwrites
    source_ref       TEXT,                        -- e.g. 'lecun/course-2#lesson-2.2'
    confidence       REAL NOT NULL DEFAULT 0.5,
    version          INT  NOT NULL DEFAULT 1,
    quality_signals  JSONB NOT NULL DEFAULT '{}', -- engagement / confusion / upvotes, accreted from interactions
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_nodes_embedding ON canonical_nodes
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- ----------------------------------------------------------------------------
--  EDGE — the web. Weights accrete every time a learner traverses an edge.
--  type: 'next_in_spine'|'prerequisite'|'elaborates'|'applies'|'contrasts'|'rabbit_hole'
-- ----------------------------------------------------------------------------
CREATE TABLE edges (
    id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    src_node   UUID NOT NULL REFERENCES canonical_nodes(id) ON DELETE CASCADE,
    dst_node   UUID NOT NULL REFERENCES canonical_nodes(id) ON DELETE CASCADE,
    type       TEXT NOT NULL,
    weight     REAL NOT NULL DEFAULT 1.0,
    origin     TEXT NOT NULL DEFAULT 'authored',  -- 'authored'|'ai_generated'|'learner_path'
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (src_node, dst_node, type)
);
CREATE INDEX idx_edges_src ON edges(src_node);
CREATE INDEX idx_edges_dst ON edges(dst_node);

-- ----------------------------------------------------------------------------
--  SPINE — an ordered path through the web (authored, ai_generated, or emergent).
-- ----------------------------------------------------------------------------
CREATE TABLE spines (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title         TEXT NOT NULL,
    subject       TEXT NOT NULL,
    description   TEXT,
    origin        TEXT NOT NULL DEFAULT 'authored',
    node_sequence JSONB NOT NULL DEFAULT '[]',     -- ordered array of node ids
    source_ref    TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ----------------------------------------------------------------------------
--  USER — lifted from carecore/havencore JWT/RBAC. role: 'learner'|'author'|'admin'
-- ----------------------------------------------------------------------------
CREATE TABLE users (
    id   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    role TEXT NOT NULL DEFAULT 'learner'
);

-- ----------------------------------------------------------------------------
--  CHECKOUT — a personal learning space. Instantiates an overlay over a spine
--  (or free-roam). Holds the companion's memory OF THIS LEARNER for this subject.
-- ----------------------------------------------------------------------------
CREATE TABLE checkouts (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id          UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    spine_id         UUID REFERENCES spines(id),       -- nullable for free-roam
    subject          TEXT,
    companion_memory JSONB NOT NULL DEFAULT '{}',
    status           TEXT NOT NULL DEFAULT 'active',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ----------------------------------------------------------------------------
--  NODE_STATE — per-learner mastery + spaced-repetition schedule + private notes.
-- ----------------------------------------------------------------------------
CREATE TABLE node_states (
    checkout_id    UUID NOT NULL REFERENCES checkouts(id) ON DELETE CASCADE,
    node_id        UUID NOT NULL REFERENCES canonical_nodes(id) ON DELETE CASCADE,
    mastery        REAL NOT NULL DEFAULT 0.0,    -- fuzzy 0..1, inferred from dialogue
    explained_back BOOLEAN NOT NULL DEFAULT FALSE,
    confusion_count INT NOT NULL DEFAULT 0,
    last_seen      TIMESTAMPTZ,
    next_review_at TIMESTAMPTZ,
    learner_notes  TEXT,
    PRIMARY KEY (checkout_id, node_id)
);

-- ----------------------------------------------------------------------------
--  INTERACTION_EVENT — the signal stream the mastery model + Librarian read from.
--  TimescaleDB hypertable on comet.
--  event_type: 'viewed'|'hook_engaged'|'asked_question'|'explained_back'|
--              'confused'|'rabbit_hole_followed'|'recall_attempt'
-- ----------------------------------------------------------------------------
CREATE TABLE interaction_events (
    ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
    checkout_id UUID NOT NULL,
    node_id     UUID,
    event_type  TEXT NOT NULL,
    payload     JSONB NOT NULL DEFAULT '{}'
);
-- SELECT create_hypertable('interaction_events','ts');   -- run after timescaledb is enabled
CREATE INDEX idx_events_checkout ON interaction_events(checkout_id, ts DESC);

"""tables.py — SQLAlchemy Core mirror of artifacts/schema.sql.

The DDL in artifacts/schema.sql is authoritative (it is the alembic baseline and
the docker initdb script). These Core Table objects are a typed handle for the
seams to build queries against — they do not create or own the schema.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    Float,
    Integer,
    MetaData,
    Table,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID

from pgvector.sqlalchemy import Vector

from .config import get_settings

metadata = MetaData()

_EMBED_DIM = get_settings().embed_dim

_uuid_pk = lambda: Column(  # noqa: E731 - tiny factory keeps the table defs readable
    "id",
    UUID(as_uuid=True),
    primary_key=True,
    server_default=text("uuid_generate_v4()"),
)

sources = Table(
    "sources",
    metadata,
    _uuid_pk(),
    Column("kind", Text, nullable=False),
    Column("title", Text, nullable=False),
    Column("uri", Text),
    Column("raw_content", Text),
    Column("ingested_at", TIMESTAMP(timezone=True), server_default=text("now()")),
)

canonical_nodes = Table(
    "canonical_nodes",
    metadata,
    _uuid_pk(),
    Column("canonical_key", Text, nullable=False, unique=True),
    Column("title", Text, nullable=False),
    Column("kind", Text, nullable=False, server_default=text("'concept'")),
    Column("hook", Text),
    Column("body", Text),
    Column("apply_prompt", Text),
    Column("recall_prompts", JSONB, nullable=False, server_default=text("'[]'")),
    Column("mastery_criteria", JSONB, nullable=False, server_default=text("'[]'")),
    Column("depth_level", Text),
    Column("embedding", Vector(_EMBED_DIM)),
    Column("origin", Text, nullable=False, server_default=text("'ai_generated'")),
    Column("locked", Boolean, nullable=False, server_default=text("false")),
    Column("source_ref", Text),
    Column("confidence", Float, nullable=False, server_default=text("0.5")),
    Column("version", Integer, nullable=False, server_default=text("1")),
    Column("quality_signals", JSONB, nullable=False, server_default=text("'{}'")),
    Column("created_at", TIMESTAMP(timezone=True), server_default=text("now()")),
    Column("updated_at", TIMESTAMP(timezone=True), server_default=text("now()")),
)

edges = Table(
    "edges",
    metadata,
    _uuid_pk(),
    Column("src_node", UUID(as_uuid=True), nullable=False),
    Column("dst_node", UUID(as_uuid=True), nullable=False),
    Column("type", Text, nullable=False),
    Column("weight", Float, nullable=False, server_default=text("1.0")),
    Column("origin", Text, nullable=False, server_default=text("'authored'")),
    Column("created_at", TIMESTAMP(timezone=True), server_default=text("now()")),
)

spines = Table(
    "spines",
    metadata,
    _uuid_pk(),
    Column("title", Text, nullable=False),
    Column("subject", Text, nullable=False),
    Column("description", Text),
    Column("origin", Text, nullable=False, server_default=text("'authored'")),
    Column("node_sequence", JSONB, nullable=False, server_default=text("'[]'")),
    Column("source_ref", Text),
    Column("created_at", TIMESTAMP(timezone=True), server_default=text("now()")),
)

users = Table(
    "users",
    metadata,
    _uuid_pk(),
    Column("role", Text, nullable=False, server_default=text("'learner'")),
)

checkouts = Table(
    "checkouts",
    metadata,
    _uuid_pk(),
    Column("user_id", UUID(as_uuid=True), nullable=False),
    Column("spine_id", UUID(as_uuid=True)),
    Column("subject", Text),
    Column("companion_memory", JSONB, nullable=False, server_default=text("'{}'")),
    Column("status", Text, nullable=False, server_default=text("'active'")),
    Column("created_at", TIMESTAMP(timezone=True), server_default=text("now()")),
)

node_states = Table(
    "node_states",
    metadata,
    Column("checkout_id", UUID(as_uuid=True), primary_key=True),
    Column("node_id", UUID(as_uuid=True), primary_key=True),
    Column("mastery", Float, nullable=False, server_default=text("0.0")),
    Column("explained_back", Boolean, nullable=False, server_default=text("false")),
    Column("confusion_count", Integer, nullable=False, server_default=text("0")),
    Column("last_seen", TIMESTAMP(timezone=True)),
    Column("next_review_at", TIMESTAMP(timezone=True)),
    Column("learner_notes", Text),
)

# interaction_events has no primary key in the schema (it becomes a Timescale
# hypertable on ts). Core tolerates a PK-less table; Phase 1 does not write here.
interaction_events = Table(
    "interaction_events",
    metadata,
    Column("ts", TIMESTAMP(timezone=True), server_default=text("now()")),
    Column("checkout_id", UUID(as_uuid=True), nullable=False),
    Column("node_id", UUID(as_uuid=True)),
    Column("event_type", Text, nullable=False),
    Column("payload", JSONB, nullable=False, server_default=text("'{}'")),
)

__all__ = [
    "metadata",
    "sources",
    "canonical_nodes",
    "edges",
    "spines",
    "users",
    "checkouts",
    "node_states",
    "interaction_events",
]

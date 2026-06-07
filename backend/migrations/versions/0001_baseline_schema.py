"""baseline schema — apply artifacts/schema.sql

The handoff's schema.sql is authoritative DDL (pgvector + the graph/overlay/event
tables). This baseline applies it verbatim. It is a no-op when the schema is
already present — e.g. the docker db image applies schema.sql via initdb, so a
fresh container is already at this revision (stamp it: `alembic stamp head`).

Revision ID: 0001_baseline
Revises:
"""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None

# backend/migrations/versions/this.py -> repo root is parents[3]
SCHEMA_SQL = Path(__file__).resolve().parents[3] / "artifacts" / "schema.sql"

_TABLES = [
    "interaction_events",
    "node_states",
    "checkouts",
    "users",
    "spines",
    "edges",
    "canonical_nodes",
    "sources",
]


def _statements(sql: str) -> list[str]:
    """Split schema.sql into individual statements. Line comments (`--`) are
    stripped; schema.sql contains no string literals with embedded `--` or `;`."""
    no_comments = "\n".join(line.split("--", 1)[0] for line in sql.splitlines())
    return [s.strip() for s in no_comments.split(";") if s.strip()]


def upgrade() -> None:
    bind = op.get_bind()
    already = bind.execute(
        sa.text("SELECT to_regclass('public.canonical_nodes')")
    ).scalar()
    if already is not None:
        return  # schema already present (e.g. applied by docker initdb)
    for statement in _statements(SCHEMA_SQL.read_text()):
        op.execute(statement)


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")

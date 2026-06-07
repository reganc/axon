"""polymorphic nodes: attributes column + kind index

Phase 5. Node type becomes first-class. `kind` is already TEXT, so the new kinds
need no DDL — this only adds a type-specific `attributes` JSONB column and an
index for type-filtered queries. Backward-compatible: existing rows get
attributes = '{}' and keep their kind.

Revision ID: 0003_polymorphic_nodes
Revises: 0002_events_hypertable
"""

from __future__ import annotations

from alembic import op

revision = "0003_polymorphic_nodes"
down_revision = "0002_events_hypertable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE canonical_nodes "
        "ADD COLUMN IF NOT EXISTS attributes JSONB NOT NULL DEFAULT '{}'"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_nodes_kind ON canonical_nodes (kind)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_nodes_kind")
    op.execute("ALTER TABLE canonical_nodes DROP COLUMN IF EXISTS attributes")

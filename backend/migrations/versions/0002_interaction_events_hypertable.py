"""interaction_events -> Timescale hypertable

Phase 2: the mastery model + Librarian read the interaction event stream. Promote
`interaction_events` to a hypertable partitioned on `ts`. Guarded — if the
timescaledb extension isn't installed (plain Postgres), it stays a normal table
and everything still works.

Revision ID: 0002_events_hypertable
Revises: 0001_baseline
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_events_hypertable"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    has_ts = bind.execute(
        sa.text("SELECT 1 FROM pg_extension WHERE extname = 'timescaledb'")
    ).scalar()
    if not has_ts:
        return
    op.execute(
        "SELECT create_hypertable('interaction_events', 'ts', "
        "if_not_exists => TRUE, migrate_data => TRUE)"
    )


def downgrade() -> None:
    # A hypertable can't be cleanly reverted to a plain table in place; leaving it
    # as-is is harmless (it still behaves like a table). No-op.
    pass

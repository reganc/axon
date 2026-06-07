"""usage_events — the LLM cost ledger

Cost control (specs/06): every cloud LLM call is metered here so per-session /
per-user-day / global-day budgets can be enforced and spend audited.

Revision ID: 0004_usage_events
Revises: 0003_polymorphic_nodes
"""

from __future__ import annotations

from alembic import op

revision = "0004_usage_events"
down_revision = "0003_polymorphic_nodes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS usage_events (
            id                  BIGSERIAL PRIMARY KEY,
            ts                  TIMESTAMPTZ NOT NULL DEFAULT now(),
            task                TEXT NOT NULL,
            role                TEXT NOT NULL,
            tier                TEXT NOT NULL,
            model               TEXT,
            input_tokens        INT  NOT NULL DEFAULT 0,
            cached_input_tokens INT  NOT NULL DEFAULT 0,
            output_tokens       INT  NOT NULL DEFAULT 0,
            cost_usd            DOUBLE PRECISION NOT NULL DEFAULT 0,
            checkout_id         UUID,
            user_id             UUID
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_usage_user_ts ON usage_events (user_id, ts DESC)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_usage_ts ON usage_events (ts DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS usage_events")

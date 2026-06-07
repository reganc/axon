"""conversation_events — durable per-checkout transcript + canvas event log

So a learning session survives the browser tab (and is resumable on another
device): every meaningful companion stream event (say/ask/node.create/
node.update/edge.create) is appended here and replayed on load.

Revision ID: 0005_conversation_events
Revises: 0004_usage_events
"""

from __future__ import annotations

from alembic import op

revision = "0005_conversation_events"
down_revision = "0004_usage_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS conversation_events (
            id          BIGSERIAL PRIMARY KEY,
            checkout_id UUID NOT NULL REFERENCES checkouts(id) ON DELETE CASCADE,
            ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
            type        TEXT NOT NULL,
            data        JSONB NOT NULL DEFAULT '{}'
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_conversation_checkout "
        "ON conversation_events (checkout_id, id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS conversation_events")

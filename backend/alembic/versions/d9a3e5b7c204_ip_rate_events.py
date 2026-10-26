"""Database-backed per-IP sign-in/registration limit: ip_rate_events

Revision ID: d9a3e5b7c204
Revises: c71f0e93d5a2
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d9a3e5b7c204"
down_revision: str | Sequence[str] | None = "c71f0e93d5a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ip_rate_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("ip_key", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ip_rate_events_scope_key", "ip_rate_events", ["scope", "ip_key"])
    op.create_index("ix_ip_rate_events_expires_at", "ip_rate_events", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_ip_rate_events_expires_at", table_name="ip_rate_events")
    op.drop_index("ix_ip_rate_events_scope_key", table_name="ip_rate_events")
    op.drop_table("ip_rate_events")

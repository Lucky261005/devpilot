"""Database-backed per-user review quota: review_quota_events

Revision ID: f2d8b4c6a913
Revises: e5c1a7f3b820
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f2d8b4c6a913"
down_revision: str | Sequence[str] | None = "e5c1a7f3b820"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "review_quota_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_review_quota_events_user_id", "review_quota_events", ["user_id"])
    op.create_index("ix_review_quota_events_expires_at", "review_quota_events", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_review_quota_events_expires_at", table_name="review_quota_events")
    op.drop_index("ix_review_quota_events_user_id", table_name="review_quota_events")
    op.drop_table("review_quota_events")

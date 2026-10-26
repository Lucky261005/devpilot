"""Installation-wide review cap: review_admissions

Revision ID: c71f0e93d5a2
Revises: b4e8d2a61f37
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c71f0e93d5a2"
down_revision: str | Sequence[str] | None = "b4e8d2a61f37"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "review_admissions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_review_admissions_created_at", "review_admissions", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_review_admissions_created_at", table_name="review_admissions")
    op.drop_table("review_admissions")

"""Database-backed per-user repository import quota: import_events

Revision ID: e5c1a7f3b820
Revises: d9a3e5b7c204
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5c1a7f3b820"
down_revision: str | Sequence[str] | None = "d9a3e5b7c204"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "import_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_import_events_user_id", "import_events", ["user_id"])
    op.create_index("ix_import_events_expires_at", "import_events", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_import_events_expires_at", table_name="import_events")
    op.drop_index("ix_import_events_user_id", table_name="import_events")
    op.drop_table("import_events")

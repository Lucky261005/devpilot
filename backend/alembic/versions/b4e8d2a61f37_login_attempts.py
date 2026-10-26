"""Per-account sign-in throttle: login_attempts

Revision ID: b4e8d2a61f37
Revises: 7a1f2c9d4e10
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b4e8d2a61f37"
down_revision: str | Sequence[str] | None = "7a1f2c9d4e10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "login_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_key", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_login_attempts_account_key", "login_attempts", ["account_key"])
    op.create_index("ix_login_attempts_created_at", "login_attempts", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_login_attempts_created_at", table_name="login_attempts")
    op.drop_index("ix_login_attempts_account_key", table_name="login_attempts")
    op.drop_table("login_attempts")

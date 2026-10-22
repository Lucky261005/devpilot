"""GitHub App token expiry and the imported branch/commit

Revision ID: 7a1f2c9d4e10
Revises: 3c3abb209ebc
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7a1f2c9d4e10"
down_revision: str | Sequence[str] | None = "3c3abb209ebc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("github_accounts") as t:
        t.add_column(sa.Column("encrypted_refresh_token", sa.Text(), nullable=True))
        t.add_column(sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True))
        t.add_column(sa.Column("refresh_expires_at", sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table("repositories") as t:
        t.add_column(sa.Column("source_branch", sa.String(length=255), nullable=True))
        t.add_column(sa.Column("source_sha", sa.String(length=40), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("repositories") as t:
        t.drop_column("source_sha")
        t.drop_column("source_branch")
    with op.batch_alter_table("github_accounts") as t:
        t.drop_column("refresh_expires_at")
        t.drop_column("token_expires_at")
        t.drop_column("encrypted_refresh_token")

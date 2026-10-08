"""add email_verified_at to users

Revision ID: c9e4b7a2d160
Revises: b3f8a1d7c952
Create Date: 2026-10-09 12:00:00.000000

A new account has to confirm its email before logging in. Existing users are
stamped as verified on upgrade, otherwise this migration would lock everyone
(the owner included) out of an account that has been working for months.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c9e4b7a2d160'
down_revision: str | Sequence[str] | None = 'b3f8a1d7c952'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute("UPDATE users SET email_verified_at = now()")


def downgrade() -> None:
    op.drop_column("users", "email_verified_at")

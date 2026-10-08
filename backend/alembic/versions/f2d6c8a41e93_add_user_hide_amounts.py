"""add hide_amounts to users

Revision ID: f2d6c8a41e93
Revises: e9b4c7d2a518
Create Date: 2026-10-08 20:00:00.000000

A per-account display preference: mask every amount in the UI. It lives on
the user rather than in localStorage so it follows the account across
devices and survives a logout. Existing users start with amounts visible.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f2d6c8a41e93'
down_revision: str | Sequence[str] | None = 'e9b4c7d2a518'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("hide_amounts", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("users", "hide_amounts")

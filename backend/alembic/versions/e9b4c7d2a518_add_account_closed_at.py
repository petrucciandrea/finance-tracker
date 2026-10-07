"""add closed_at to accounts

Revision ID: e9b4c7d2a518
Revises: c5e9a2d73f18
Create Date: 2026-10-08 18:00:00.000000

A closed account keeps its history and its place in balances, but takes no
movement dated after the closing day. NULL means open — every existing
account starts that way.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e9b4c7d2a518'
down_revision: str | Sequence[str] | None = 'c5e9a2d73f18'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("closed_at", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("accounts", "closed_at")

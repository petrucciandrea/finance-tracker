"""add approval_status to users

Revision ID: a7d2e9c4b861
Revises: c4b8e2f61a37
Create Date: 2026-10-08 21:00:00.000000

Gate for registration: with REGISTRATION_MODE=approval a new account starts
`pending` and can't log in until the admin approves it. Every existing user
becomes `approved` (the server default) — locking the owner out of their own
account on deploy would be the one unforgivable outcome of this migration.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a7d2e9c4b861'
down_revision: str | Sequence[str] | None = 'c4b8e2f61a37'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "approval_status", sa.String(length=10), server_default="approved", nullable=False
        ),
    )
    op.create_check_constraint(
        "ck_users_approval_status",
        "users",
        "approval_status in ('pending','approved','rejected')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_approval_status", "users", type_="check")
    op.drop_column("users", "approval_status")

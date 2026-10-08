"""add terms acceptance to users

Revision ID: b3f8a1d7c952
Revises: a7d2e9c4b861
Create Date: 2026-10-09 10:00:00.000000

Records when, and which version of, the privacy policy + terms a user accepted
at registration. Existing users stay NULL: they were never shown the checkbox.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3f8a1d7c952"
down_revision: str | Sequence[str] | None = "a7d2e9c4b861"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("users", sa.Column("terms_version", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "terms_version")
    op.drop_column("users", "terms_accepted_at")

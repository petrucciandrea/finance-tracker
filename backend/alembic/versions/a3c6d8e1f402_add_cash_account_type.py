"""add cash account type

Revision ID: a3c6d8e1f402
Revises: a0c46d1e8b73
Create Date: 2026-10-07 10:00:00.000000

Physical cash gets its own account type rather than living in a "checking"
account named "Contanti", so the UI can group and label it. No new tables:
a withdrawal is a giroconto into the cash account, cash spending is an
ordinary expense on it.
"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a3c6d8e1f402'
down_revision: str | Sequence[str] | None = 'a0c46d1e8b73'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_accounts_type", "accounts", type_="check")
    op.create_check_constraint(
        "ck_accounts_type",
        "accounts",
        "type in ('checking','savings','credit_card','investment','crypto_wallet','cash')",
    )


def downgrade() -> None:
    # Fails while any cash account exists, deliberately: silently retyping
    # them to 'checking' would lose information the user chose to record.
    op.drop_constraint("ck_accounts_type", "accounts", type_="check")
    op.create_check_constraint(
        "ck_accounts_type",
        "accounts",
        "type in ('checking','savings','credit_card','investment','crypto_wallet')",
    )

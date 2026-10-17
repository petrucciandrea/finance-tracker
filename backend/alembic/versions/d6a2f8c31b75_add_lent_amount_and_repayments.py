"""add lent_amount and repays_transaction_id to transactions

Revision ID: d6a2f8c31b75
Revises: c9e4b7a2d160
Create Date: 2026-10-17 12:00:00.000000

An expense can record how much of it was fronted for other people; an income
can say which expense it pays back. Both start NULL, so every existing row
reads exactly as before. Additive on purpose: the deploy runs migrations
before the new code, and the old code ignores both columns.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd6a2f8c31b75'
down_revision: str | Sequence[str] | None = 'c9e4b7a2d160'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("transactions", sa.Column("lent_amount", sa.Numeric(18, 8), nullable=True))
    op.add_column(
        "transactions",
        sa.Column("repays_transaction_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_transactions_repays_transaction_id",
        "transactions",
        "transactions",
        ["repays_transaction_id"],
        ["id"],
    )
    op.create_index(
        "ix_transactions_repays_transaction_id", "transactions", ["repays_transaction_id"]
    )
    op.create_check_constraint(
        "ck_transactions_lent_amount",
        "transactions",
        "lent_amount IS NULL OR "
        "(type = 'expense' AND lent_amount > 0 AND lent_amount <= abs(amount))",
    )
    op.create_check_constraint(
        "ck_transactions_repays_income_only",
        "transactions",
        "repays_transaction_id IS NULL OR (type = 'income' AND repays_transaction_id <> id)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_transactions_repays_income_only", "transactions", type_="check")
    op.drop_constraint("ck_transactions_lent_amount", "transactions", type_="check")
    op.drop_index("ix_transactions_repays_transaction_id", table_name="transactions")
    op.drop_constraint("fk_transactions_repays_transaction_id", "transactions", type_="foreignkey")
    op.drop_column("transactions", "repays_transaction_id")
    op.drop_column("transactions", "lent_amount")

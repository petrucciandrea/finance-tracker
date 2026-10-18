"""add offset_transaction_id to transactions

Revision ID: a3c5e7b91d24
Revises: d6a2f8c31b75
Create Date: 2026-10-18 12:00:00.000000

A credit can be settled in kind (the friend pays for the next dinner instead
of handing cash back): two rows on one account that cancel out in cash, an
expense for the user's own share and the repayment closing the credit. This
column points each leg at the other so they are deleted together. NULL
everywhere else. Additive on purpose: the deploy runs migrations before the
new code, and the old code ignores the column.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a3c5e7b91d24'
down_revision: str | Sequence[str] | None = 'd6a2f8c31b75'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column("offset_transaction_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_transactions_offset_transaction_id",
        "transactions",
        "transactions",
        ["offset_transaction_id"],
        ["id"],
    )
    op.create_index(
        "ix_transactions_offset_transaction_id", "transactions", ["offset_transaction_id"]
    )
    op.create_check_constraint(
        "ck_transactions_offset_not_self",
        "transactions",
        "offset_transaction_id IS NULL OR offset_transaction_id <> id",
    )


def downgrade() -> None:
    op.drop_constraint("ck_transactions_offset_not_self", "transactions", type_="check")
    op.drop_index("ix_transactions_offset_transaction_id", table_name="transactions")
    op.drop_constraint("fk_transactions_offset_transaction_id", "transactions", type_="foreignkey")
    op.drop_column("transactions", "offset_transaction_id")

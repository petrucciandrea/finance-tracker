"""add transaction_id to asset_transactions

Revision ID: 72d8347009eb
Revises: a34605bda5f6
Create Date: 2026-09-13 16:00:47.370909

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '72d8347009eb'
down_revision: str | Sequence[str] | None = 'a34605bda5f6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('asset_transactions', sa.Column('transaction_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f('asset_transactions_transaction_id_fkey'),
        'asset_transactions',
        'transactions',
        ['transaction_id'],
        ['id'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        op.f('asset_transactions_transaction_id_fkey'), 'asset_transactions', type_='foreignkey'
    )
    op.drop_column('asset_transactions', 'transaction_id')

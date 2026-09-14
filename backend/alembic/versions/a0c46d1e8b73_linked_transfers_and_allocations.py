"""link transfer legs and record savings allocations

Revision ID: a0c46d1e8b73
Revises: f7b3a9e0c215
Create Date: 2026-09-14 15:30:00.000000

Phase D: executing the waterfall's suggestions.

A real A->B giroconto has always been two unrelated rows — delete one and
the other is orphaned, leaving the balances wrong. `counterpart_transaction_id`
pairs them, mirroring what `asset_transactions.transaction_id` already does
for a buy/sell's cash leg.

The invariant is "a transfer MAY have a counterpart", never "has one":
every pre-existing row, plus every future opening balance and portfolio
cash leg, has NULL here.

`savings_allocations` records what a period's quota has already been spent
on, so reloading the page doesn't offer the same money twice.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a0c46d1e8b73'
down_revision: str | Sequence[str] | None = 'f7b3a9e0c215'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'transactions', sa.Column('counterpart_transaction_id', sa.UUID(), nullable=True)
    )
    op.create_foreign_key(
        'fk_transactions_counterpart',
        'transactions',
        'transactions',
        ['counterpart_transaction_id'],
        ['id'],
    )
    op.create_check_constraint(
        'ck_transactions_counterpart_not_self',
        'transactions',
        'counterpart_transaction_id IS NULL OR counterpart_transaction_id <> id',
    )
    # A leg can only be claimed once, so two rows can't both point at the
    # same partner and leave a three-way tangle.
    op.create_index(
        'uq_transactions_counterpart',
        'transactions',
        ['counterpart_transaction_id'],
        unique=True,
        postgresql_where=sa.text('counterpart_transaction_id IS NOT NULL'),
    )

    op.create_table(
        'savings_allocations',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('goal_id', sa.UUID(), nullable=False),
        # The destination leg. Deleting it soft-deletes this row too, or the
        # allocation would consume the period's quota forever.
        sa.Column('transaction_id', sa.UUID(), nullable=False),
        sa.Column('period_start', sa.Date(), nullable=False),
        sa.Column('amount_base_currency', sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['goal_id'], ['savings_goals.id'], ),
        sa.ForeignKeyConstraint(['transaction_id'], ['transactions.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_savings_allocations_user_id'), 'savings_allocations', ['user_id'], unique=False
    )
    op.create_index(
        op.f('ix_savings_allocations_goal_id'), 'savings_allocations', ['goal_id'], unique=False
    )
    op.create_index(
        op.f('ix_savings_allocations_period_start'),
        'savings_allocations',
        ['period_start'],
        unique=False,
    )
    op.create_index(
        op.f('ix_savings_allocations_transaction_id'),
        'savings_allocations',
        ['transaction_id'],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f('ix_savings_allocations_transaction_id'), table_name='savings_allocations'
    )
    op.drop_index(op.f('ix_savings_allocations_period_start'), table_name='savings_allocations')
    op.drop_index(op.f('ix_savings_allocations_goal_id'), table_name='savings_allocations')
    op.drop_index(op.f('ix_savings_allocations_user_id'), table_name='savings_allocations')
    op.drop_table('savings_allocations')

    op.drop_index('uq_transactions_counterpart', table_name='transactions')
    op.drop_constraint('ck_transactions_counterpart_not_self', 'transactions', type_='check')
    op.drop_constraint('fk_transactions_counterpart', 'transactions', type_='foreignkey')
    op.drop_column('transactions', 'counterpart_transaction_id')

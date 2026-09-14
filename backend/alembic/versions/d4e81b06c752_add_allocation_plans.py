"""add allocation plans

Revision ID: d4e81b06c752
Revises: c1a7f2e94b30
Create Date: 2026-09-14 11:05:00.000000

Phase B of the cascading planning engine: the 50/25/15/10 allocation model.

No rows are created here. A plan is get-or-created with the preset on the
user's first read, the same lazy pattern as the "Varie" category — so
existing users need no backfill and no user can end up without a plan.

Deliberately NO unique index on user_id. It would turn two concurrent
first reads into an IntegrityError surfacing as a generic 500; the "Varie"
precedent works precisely because a duplicate row is harmless. The
singleton is obtained by selecting the oldest surviving row instead.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd4e81b06c752'
down_revision: str | Sequence[str] | None = 'c1a7f2e94b30'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'allocation_plans',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('pct_primary', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('pct_useful', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('pct_discretionary', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('pct_savings', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('lookback_months', sa.Integer(), nullable=False, server_default='6'),
        sa.Column('default_source_account_id', sa.UUID(), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['default_source_account_id'], ['accounts.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            'pct_primary + pct_useful + pct_discretionary + pct_savings = 100',
            name='ck_allocation_plans_percentages_sum',
        ),
        sa.CheckConstraint('lookback_months between 1 and 60', name='ck_allocation_plans_lookback'),
    )
    op.create_index(
        op.f('ix_allocation_plans_user_id'), 'allocation_plans', ['user_id'], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_allocation_plans_user_id'), table_name='allocation_plans')
    op.drop_table('allocation_plans')

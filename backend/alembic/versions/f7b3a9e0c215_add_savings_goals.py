"""add savings goals and their funding sources

Revision ID: f7b3a9e0c215
Revises: e5f92c1a7d84
Create Date: 2026-09-14 14:10:00.000000

Phase C of the planning engine: the rungs of the savings waterfall.

Two constraints are deliberately absent from the schema:

- No unique index on (user_id, priority). Postgres checks unique indexes
  per statement and the ORM emits row-by-row UPDATEs, so swapping two
  priorities would always collide halfway through; a partial index can't
  be DEFERRABLE either. Ordering is (priority, created_at), which is
  deterministic even when two rungs share a priority.

- No constraint that an account funds at most one goal. The scope of that
  rule is the user, not the goal, so it isn't expressible as a unique
  index on this table — the router enforces it with a 409.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f7b3a9e0c215'
down_revision: str | Sequence[str] | None = 'e5f92c1a7d84'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'savings_goals',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False),
        sa.Column('target_mode', sa.String(length=30), nullable=False),
        sa.Column('target_months', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('target_amount', sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            "kind in ('emergency_fund','medium_term','long_term')",
            name='ck_savings_goals_kind',
        ),
        sa.CheckConstraint(
            "target_mode in ('months_of_primary_expenses','fixed_amount','open_ended')",
            name='ck_savings_goals_target_mode',
        ),
        # Each mode carries exactly the parameter it needs and no other, so
        # an impossible combination can't be stored at all.
        sa.CheckConstraint(
            "(target_mode = 'months_of_primary_expenses'"
            "  AND target_months IS NOT NULL AND target_amount IS NULL)"
            " OR (target_mode = 'fixed_amount'"
            "  AND target_amount IS NOT NULL AND target_months IS NULL)"
            " OR (target_mode = 'open_ended'"
            "  AND target_months IS NULL AND target_amount IS NULL)",
            name='ck_savings_goals_target_parameters',
        ),
        sa.CheckConstraint('priority >= 0', name='ck_savings_goals_priority'),
    )
    op.create_index(
        op.f('ix_savings_goals_user_id'), 'savings_goals', ['user_id'], unique=False
    )

    op.create_table(
        'savings_goal_sources',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('goal_id', sa.UUID(), nullable=False),
        sa.Column('account_id', sa.UUID(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['goal_id'], ['savings_goals.id'], ),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_savings_goal_sources_goal_id'),
        'savings_goal_sources',
        ['goal_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_savings_goal_sources_account_id'),
        'savings_goal_sources',
        ['account_id'],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f('ix_savings_goal_sources_account_id'), table_name='savings_goal_sources'
    )
    op.drop_index(op.f('ix_savings_goal_sources_goal_id'), table_name='savings_goal_sources')
    op.drop_table('savings_goal_sources')
    op.drop_index(op.f('ix_savings_goals_user_id'), table_name='savings_goals')
    op.drop_table('savings_goals')

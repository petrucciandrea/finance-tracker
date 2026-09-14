"""enforce one budget per category and period

Revision ID: e5f92c1a7d84
Revises: d4e81b06c752
Create Date: 2026-09-14 12:40:00.000000

Nothing stopped two active budgets on the same category and period, and
/budgets/status returned them as two rows the client could not tell apart
(BudgetStatus carried no budget_id). Duplicates are soft-deleted here,
newest kept, and a partial unique index stops new ones.

The index is partial on `deleted_at IS NULL` so a soft-deleted budget
never blocks recreating one for the same category — which is precisely how
a user "changes" a budget's frozen fields today.
"""
from collections.abc import Sequence

from sqlalchemy import text as sa_text

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e5f92c1a7d84'
down_revision: str | Sequence[str] | None = 'd4e81b06c752'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _soft_delete_duplicate_budgets(bind) -> None:
    """
    Keep the most recently started budget per (user, category, period);
    soft-delete the rest. `budgets` has no created_at, so start_date is the
    best available proxy for "most recent", with the id as a deterministic
    tiebreaker.
    """
    bind.execute(
        sa_text(
            """
            UPDATE budgets
               SET deleted_at = now()
             WHERE deleted_at IS NULL
               AND id NOT IN (
                   SELECT DISTINCT ON (user_id, category_id, period) id
                     FROM budgets
                    WHERE deleted_at IS NULL
                 ORDER BY user_id, category_id, period, start_date DESC, id DESC
               )
            """
        )
    )


def upgrade() -> None:
    """Upgrade schema."""
    _soft_delete_duplicate_budgets(op.get_bind())
    op.create_index(
        'uq_budgets_active_category_period',
        'budgets',
        ['user_id', 'category_id', 'period'],
        unique=True,
        postgresql_where=sa_text('deleted_at IS NULL'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    # The soft-deleted duplicates are deliberately not resurrected: which
    # rows this migration retired isn't recorded, and reviving them would
    # be guesswork.
    op.drop_index('uq_budgets_active_category_period', table_name='budgets')

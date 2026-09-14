"""add necessity taxonomy and income base flag

Revision ID: c1a7f2e94b30
Revises: b70191ae0c34
Create Date: 2026-09-14 09:20:00.000000

Phase A of the cascading planning engine. Purely additive:

- `categories.necessity_level` / `transactions.necessity_level_override` are
  nullable, so every existing row starts as "unclassified". There is
  deliberately NO backfill to 'primary': classifying historical spend by
  fiat would produce a survival budget and an emergency-fund target that
  look plausible and are wrong, which is worse than an obviously
  incomplete one.
- `categories.excluded_from_income_base` defaults to false, so the income
  base is unchanged until the user opts a category out.

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c1a7f2e94b30'
down_revision: str | Sequence[str] | None = 'b70191ae0c34'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_NECESSITY_DOMAIN = "in ('primary','useful','discretionary')"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'categories', sa.Column('necessity_level', sa.String(length=20), nullable=True)
    )
    op.add_column(
        'categories',
        sa.Column(
            'excluded_from_income_base',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        'transactions',
        sa.Column('necessity_level_override', sa.String(length=20), nullable=True),
    )

    # NULL passes a CHECK, so "unclassified" needs no exemption in the constraint.
    op.create_check_constraint(
        'ck_categories_necessity_level', 'categories', f'necessity_level {_NECESSITY_DOMAIN}'
    )
    op.create_check_constraint(
        'ck_transactions_necessity_level_override',
        'transactions',
        f'necessity_level_override {_NECESSITY_DOMAIN}',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        'ck_transactions_necessity_level_override', 'transactions', type_='check'
    )
    op.drop_constraint('ck_categories_necessity_level', 'categories', type_='check')
    op.drop_column('transactions', 'necessity_level_override')
    op.drop_column('categories', 'excluded_from_income_base')
    op.drop_column('categories', 'necessity_level')

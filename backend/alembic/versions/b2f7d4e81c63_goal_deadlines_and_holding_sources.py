"""savings goals with a deadline, completed goals, holdings as goal sources

Revision ID: b2f7d4e81c63
Revises: e8b4d2f6a913
Create Date: 2026-11-26 12:00:00.000000

- allocation_plans: `operating_cash_months`, pillar 1's target (months of
  average spend the unassigned accounts should hold), default 1.
- savings_goals: `target_date` (a fixed-amount, medium-term goal due on a
  date: "10k for the car in a year") and `completed_at` (the goal was
  reached and spent — unlike a drained emergency fund, it must not reopen).
- savings_goal_sources: `asset_id`. `(account)` still counts the account's
  cash; `(account, asset)` counts that holding, the same grain as
  `flat_rate_provision_sources`.

Additive: every existing goal has no date and is not completed, and every
existing source is a cash source, which is what the old code reads.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2f7d4e81c63"
down_revision: str | Sequence[str] | None = "e8b4d2f6a913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "allocation_plans",
        sa.Column("operating_cash_months", sa.Numeric(4, 1), nullable=False, server_default="1"),
    )
    op.add_column("savings_goals", sa.Column("target_date", sa.Date(), nullable=True))
    op.add_column("savings_goals", sa.Column("completed_at", sa.Date(), nullable=True))
    op.create_check_constraint(
        "ck_savings_goals_target_date",
        "savings_goals",
        "target_date IS NULL OR (kind = 'medium_term' AND target_mode = 'fixed_amount')",
    )

    op.add_column(
        "savings_goal_sources",
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_savings_goal_sources_asset_id",
        "savings_goal_sources",
        "assets",
        ["asset_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_savings_goal_sources_asset_id", "savings_goal_sources", type_="foreignkey"
    )
    op.drop_column("savings_goal_sources", "asset_id")
    op.drop_constraint("ck_savings_goals_target_date", "savings_goals", type_="check")
    op.drop_column("savings_goals", "completed_at")
    op.drop_column("savings_goals", "target_date")
    op.drop_column("allocation_plans", "operating_cash_months")

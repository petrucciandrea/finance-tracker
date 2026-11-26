"""portfolio guardrails: targets, caps, idle cash, minimum invested share

Revision ID: d3f9b6a24c81
Revises: c8a1e5f37b20
Create Date: 2026-11-26 17:00:00.000000

A new table only; nothing is created for existing users (no rule = nothing
is judged).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d3f9b6a24c81"
down_revision: str | Sequence[str] | None = "c8a1e5f37b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "portfolio_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("dimension", sa.String(12), nullable=True),
        sa.Column("bucket", sa.String(40), nullable=True),
        sa.Column("target_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("tolerance_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("max_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("min_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("threshold_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("threshold_months", sa.Numeric(4, 1), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "kind in ('target','max_share','excess_cash','min_invested')",
            name="ck_portfolio_rules_kind",
        ),
        sa.CheckConstraint(
            "(kind = 'target' AND dimension IN ('asset_class','region') AND bucket IS NOT NULL"
            "  AND target_pct IS NOT NULL AND tolerance_pct IS NOT NULL)"
            " OR (kind = 'max_share' AND dimension IS NOT NULL AND bucket IS NOT NULL"
            "  AND max_pct IS NOT NULL)"
            " OR (kind = 'excess_cash'"
            "  AND (threshold_amount IS NOT NULL) <> (threshold_months IS NOT NULL))"
            " OR (kind = 'min_invested' AND min_pct IS NOT NULL)",
            name="ck_portfolio_rules_parameters",
        ),
    )
    op.create_index("ix_portfolio_rules_user_id", "portfolio_rules", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_portfolio_rules_user_id", table_name="portfolio_rules")
    op.drop_table("portfolio_rules")

"""flat-rate years: the substitute tax rate becomes automatic when NULL

Revision ID: c4b8e2f61a37
Revises: a7e3c91d5f20
Create Date: 2026-10-08 20:00:00.000000

NULL now means "5% for the start year and the four after it, 15% after",
derived from flat_rate_settings.activity_start_date. Existing rows are reset
to automatic: the section shipped hours earlier with a hard 15% default, so
what they hold is that default rather than a choice.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c4b8e2f61a37'
down_revision: str | Sequence[str] | None = 'a7e3c91d5f20'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RATES_CHECK = (
    "profitability_coefficient > 0 AND profitability_coefficient <= 1"
    " AND {tax}"
    " AND inps_rate >= 0 AND inps_rate < 1"
    " AND rivalsa_rate >= 0 AND rivalsa_rate < 1"
    " AND (provision_rate IS NULL OR (provision_rate >= 0 AND provision_rate <= 1))"
)


def upgrade() -> None:
    op.drop_constraint("ck_flat_rate_years_rates", "flat_rate_years", type_="check")
    op.alter_column(
        "flat_rate_years", "substitute_tax_rate", existing_type=sa.Numeric(5, 4), nullable=True
    )
    op.create_check_constraint(
        "ck_flat_rate_years_rates",
        "flat_rate_years",
        _RATES_CHECK.format(
            tax="(substitute_tax_rate IS NULL"
            " OR (substitute_tax_rate >= 0 AND substitute_tax_rate < 1))"
        ),
    )
    op.execute("UPDATE flat_rate_years SET substitute_tax_rate = NULL")


def downgrade() -> None:
    op.drop_constraint("ck_flat_rate_years_rates", "flat_rate_years", type_="check")
    # Freeze each automatic rate as it reads today.
    op.execute(
        "UPDATE flat_rate_years y SET substitute_tax_rate = 0.05"
        " FROM flat_rate_settings s"
        " WHERE s.user_id = y.user_id AND y.substitute_tax_rate IS NULL"
        " AND s.activity_start_date IS NOT NULL"
        " AND y.year BETWEEN EXTRACT(YEAR FROM s.activity_start_date)"
        " AND EXTRACT(YEAR FROM s.activity_start_date) + 4"
    )
    op.execute(
        "UPDATE flat_rate_years SET substitute_tax_rate = 0.15 WHERE substitute_tax_rate IS NULL"
    )
    op.alter_column(
        "flat_rate_years", "substitute_tax_rate", existing_type=sa.Numeric(5, 4), nullable=False
    )
    op.create_check_constraint(
        "ck_flat_rate_years_rates",
        "flat_rate_years",
        _RATES_CHECK.format(tax="substitute_tax_rate >= 0 AND substitute_tax_rate < 1"),
    )

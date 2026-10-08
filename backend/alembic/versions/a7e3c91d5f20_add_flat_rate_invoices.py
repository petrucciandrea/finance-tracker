"""add work type, flat-rate (forfettario) invoices, F24 payments, provision

Revision ID: a7e3c91d5f20
Revises: f2d6c8a41e93
Create Date: 2026-10-08 18:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import text as sa_text

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a7e3c91d5f20'
down_revision: str | Sequence[str] | None = 'f2d6c8a41e93'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps(soft_delete: bool) -> list[sa.Column]:
    columns = [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        )
    ]
    if soft_delete:
        columns.append(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    return columns


def _user_fk() -> sa.Column:
    return sa.Column(
        "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
    )


def upgrade() -> None:
    op.add_column("users", sa.Column("work_type", sa.String(20), nullable=True))
    op.create_check_constraint(
        "ck_users_work_type", "users", "work_type in ('employee','flat_rate','ordinary')"
    )

    op.create_table(
        "flat_rate_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _user_fk(),
        sa.Column("activity_start_date", sa.Date(), nullable=True),
        sa.Column(
            "safety_margin", sa.Numeric(5, 4), server_default="0.15", nullable=False
        ),
        *_timestamps(soft_delete=False),
        sa.UniqueConstraint("user_id", name="uq_flat_rate_settings_user_id"),
        sa.CheckConstraint(
            "safety_margin >= 0 AND safety_margin <= 1", name="ck_flat_rate_settings_margin"
        ),
    )

    op.create_table(
        "flat_rate_years",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _user_fk(),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("profitability_coefficient", sa.Numeric(5, 4), nullable=False),
        sa.Column("substitute_tax_rate", sa.Numeric(5, 4), nullable=False),
        sa.Column("inps_rate", sa.Numeric(5, 4), nullable=False),
        sa.Column("rivalsa_rate", sa.Numeric(5, 4), nullable=False),
        sa.Column("provision_rate", sa.Numeric(5, 4), nullable=True),
        *_timestamps(soft_delete=False),
        sa.CheckConstraint(
            "profitability_coefficient > 0 AND profitability_coefficient <= 1"
            " AND substitute_tax_rate >= 0 AND substitute_tax_rate < 1"
            " AND inps_rate >= 0 AND inps_rate < 1"
            " AND rivalsa_rate >= 0 AND rivalsa_rate < 1"
            " AND (provision_rate IS NULL OR (provision_rate >= 0 AND provision_rate <= 1))",
            name="ck_flat_rate_years_rates",
        ),
    )
    op.create_index(
        "uq_flat_rate_years_user_year", "flat_rate_years", ["user_id", "year"], unique=True
    )

    op.create_table(
        "invoices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _user_fk(),
        sa.Column("number", sa.String(50), nullable=True),
        sa.Column("client", sa.String(200), nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("rivalsa_rate", sa.Numeric(5, 4), nullable=False),
        sa.Column("stamp_duty", sa.Boolean(), nullable=False),
        sa.Column("collected_on", sa.Date(), nullable=True),
        sa.Column("provision_rate", sa.Numeric(5, 4), nullable=True),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.Column(
            "transaction_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("transactions.id"),
            nullable=True,
        ),
        sa.Column("owns_transaction", sa.Boolean(), server_default=sa.false(), nullable=False),
        *_timestamps(soft_delete=True),
        sa.CheckConstraint("amount > 0", name="ck_invoices_amount"),
        sa.CheckConstraint(
            "rivalsa_rate >= 0 AND rivalsa_rate < 1", name="ck_invoices_rivalsa"
        ),
        sa.CheckConstraint(
            "provision_rate IS NULL OR (provision_rate >= 0 AND provision_rate <= 1)",
            name="ck_invoices_provision_rate",
        ),
        sa.CheckConstraint(
            "transaction_id IS NULL OR collected_on IS NOT NULL",
            name="ck_invoices_transaction_needs_collection",
        ),
        sa.CheckConstraint(
            "NOT owns_transaction OR transaction_id IS NOT NULL",
            name="ck_invoices_owned_transaction",
        ),
    )
    op.create_index("ix_invoices_user_id", "invoices", ["user_id"])
    op.create_index(
        "uq_invoices_transaction",
        "invoices",
        ["transaction_id"],
        unique=True,
        postgresql_where=sa_text("deleted_at IS NULL AND transaction_id IS NOT NULL"),
    )

    op.create_table(
        "tax_payments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _user_fk(),
        sa.Column("paid_on", sa.Date(), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("component", sa.String(20), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.Column(
            "transaction_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("transactions.id"),
            nullable=True,
        ),
        *_timestamps(soft_delete=True),
        sa.CheckConstraint("amount > 0", name="ck_tax_payments_amount"),
        sa.CheckConstraint(
            "component in ('substitute_tax','inps')", name="ck_tax_payments_component"
        ),
        sa.CheckConstraint(
            "kind in ('balance','first_advance','second_advance')", name="ck_tax_payments_kind"
        ),
    )
    op.create_index("ix_tax_payments_user_id", "tax_payments", ["user_id"])

    op.create_table(
        "flat_rate_provision_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _user_fk(),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id"),
            nullable=False,
        ),
        sa.Column(
            "asset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("assets.id"), nullable=True
        ),
        *_timestamps(soft_delete=True),
    )
    op.create_index(
        "ix_flat_rate_provision_sources_user_id", "flat_rate_provision_sources", ["user_id"]
    )


def downgrade() -> None:
    op.drop_table("flat_rate_provision_sources")
    op.drop_table("tax_payments")
    op.drop_table("invoices")
    op.drop_table("flat_rate_years")
    op.drop_table("flat_rate_settings")
    op.drop_constraint("ck_users_work_type", "users", type_="check")
    op.drop_column("users", "work_type")

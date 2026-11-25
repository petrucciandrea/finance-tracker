"""scheduled F24 payments, the bollo as an F24 line, vehicle deadlines

Revision ID: e8b4d2f6a913
Revises: a3c5e7b91d24
Create Date: 2026-11-25 12:00:00.000000

- tax_payments: `status` (scheduled/paid, every existing row is paid), the
  `account_id` a payment leaves from (backfilled from the leg), and
  `owns_transaction` (every existing leg was written by the app). The
  component/kind CHECKs widen to the bollo's quarters.
- invoices: `sdi_delivered_on`, the date the bollo's quarter follows.
- vehicle_deadlines: insurance, road tax, inspection, service.

Additive on purpose: the deploy migrates before the new code starts, and the
old code reads every existing row as it did (status defaults to paid).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e8b4d2f6a913'
down_revision: str | Sequence[str] | None = 'a3c5e7b91d24'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tax_payments",
        sa.Column("status", sa.String(10), nullable=False, server_default="paid"),
    )
    op.add_column(
        "tax_payments",
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "tax_payments",
        sa.Column("owns_transaction", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_foreign_key(
        "fk_tax_payments_account_id", "tax_payments", "accounts", ["account_id"], ["id"]
    )
    op.execute(
        "UPDATE tax_payments SET account_id = t.account_id "
        "FROM transactions t WHERE t.id = tax_payments.transaction_id"
    )
    op.create_check_constraint(
        "ck_tax_payments_status", "tax_payments", "status in ('scheduled','paid')"
    )
    op.drop_constraint("ck_tax_payments_component", "tax_payments", type_="check")
    op.create_check_constraint(
        "ck_tax_payments_component",
        "tax_payments",
        "component in ('substitute_tax','inps','stamp_duty')",
    )
    op.drop_constraint("ck_tax_payments_kind", "tax_payments", type_="check")
    op.create_check_constraint(
        "ck_tax_payments_kind",
        "tax_payments",
        "kind in ('balance','first_advance','second_advance','q1','q2','q3','q4')",
    )
    op.create_check_constraint(
        "ck_tax_payments_component_kind",
        "tax_payments",
        "(component = 'stamp_duty') = (kind in ('q1','q2','q3','q4'))",
    )
    op.create_check_constraint(
        "ck_tax_payments_scheduled",
        "tax_payments",
        "status <> 'scheduled' OR (account_id IS NOT NULL AND transaction_id IS NULL)",
    )

    op.add_column("invoices", sa.Column("sdi_delivered_on", sa.Date(), nullable=True))
    op.create_check_constraint(
        "ck_invoices_sdi_delivery",
        "invoices",
        "sdi_delivered_on IS NULL OR sdi_delivered_on >= issue_date",
    )

    op.create_table(
        "vehicle_deadlines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "physical_asset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("physical_assets.id"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("label", sa.String(100), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("currency", sa.String(3), sa.ForeignKey("currencies.code"), nullable=False),
        sa.Column(
            "account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("accounts.id"), nullable=True
        ),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.Column("done_on", sa.Date(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind in ('insurance','road_tax','inspection','service','other')",
            name="ck_vehicle_deadlines_kind",
        ),
        sa.CheckConstraint(
            "kind <> 'other' OR label IS NOT NULL", name="ck_vehicle_deadlines_label"
        ),
        sa.CheckConstraint("amount IS NULL OR amount > 0", name="ck_vehicle_deadlines_amount"),
        sa.CheckConstraint(
            "account_id IS NULL OR amount IS NOT NULL", name="ck_vehicle_deadlines_account"
        ),
    )
    op.create_index("ix_vehicle_deadlines_user_id", "vehicle_deadlines", ["user_id"])
    op.create_index(
        "ix_vehicle_deadlines_physical_asset_id", "vehicle_deadlines", ["physical_asset_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_vehicle_deadlines_physical_asset_id", table_name="vehicle_deadlines")
    op.drop_index("ix_vehicle_deadlines_user_id", table_name="vehicle_deadlines")
    op.drop_table("vehicle_deadlines")

    op.drop_constraint("ck_invoices_sdi_delivery", "invoices", type_="check")
    op.drop_column("invoices", "sdi_delivered_on")

    # Rows that only the new code can write have nowhere to go in the old schema.
    op.execute("DELETE FROM tax_payments WHERE status = 'scheduled' OR component = 'stamp_duty'")
    op.drop_constraint("ck_tax_payments_scheduled", "tax_payments", type_="check")
    op.drop_constraint("ck_tax_payments_component_kind", "tax_payments", type_="check")
    op.drop_constraint("ck_tax_payments_kind", "tax_payments", type_="check")
    op.create_check_constraint(
        "ck_tax_payments_kind",
        "tax_payments",
        "kind in ('balance','first_advance','second_advance')",
    )
    op.drop_constraint("ck_tax_payments_component", "tax_payments", type_="check")
    op.create_check_constraint(
        "ck_tax_payments_component", "tax_payments", "component in ('substitute_tax','inps')"
    )
    op.drop_constraint("ck_tax_payments_status", "tax_payments", type_="check")
    op.drop_constraint("fk_tax_payments_account_id", "tax_payments", type_="foreignkey")
    op.drop_column("tax_payments", "owns_transaction")
    op.drop_column("tax_payments", "account_id")
    op.drop_column("tax_payments", "status")

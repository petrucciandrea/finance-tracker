"""add physical assets (vehicles, precious metals)

Revision ID: b8d2f4a61c97
Revises: a3c6d8e1f402
Create Date: 2026-10-08 10:00:00.000000

Metal spot prices reuse the `assets`/`asset_prices` cache: three `metal`
rows are seeded here (COMEX futures on Yahoo Finance, USD per troy ounce),
so the existing price fetch, history backfill and per-day caching all
apply unchanged.
"""
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import text as sa_text

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b8d2f4a61c97'
down_revision: str | Sequence[str] | None = 'a3c6d8e1f402'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

METAL_ASSETS = [
    ("GC=F", "Oro (COMEX)"),
    ("SI=F", "Argento (COMEX)"),
    ("PL=F", "Platino (NYMEX)"),
]


def upgrade() -> None:
    op.drop_constraint("ck_assets_type", "assets", type_="check")
    op.create_check_constraint(
        "ck_assets_type", "assets", "asset_type in ('stock','etf','crypto','metal')"
    )
    assets = sa.table(
        "assets",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("symbol", sa.String),
        sa.column("name", sa.String),
        sa.column("asset_type", sa.String),
        sa.column("currency", sa.String),
    )
    op.bulk_insert(
        assets,
        [
            {
                "id": uuid.uuid4(),
                "symbol": symbol,
                "name": name,
                "asset_type": "metal",
                "currency": "USD",
            }
            for symbol, name in METAL_ASSETS
        ],
    )

    op.create_table(
        "physical_assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.Column("currency", sa.String(3), sa.ForeignKey("currencies.code"), nullable=False),
        sa.Column("purchase_date", sa.Date(), nullable=False),
        sa.Column("purchase_price", sa.Numeric(18, 2), nullable=True),
        sa.Column("purchase_price_base_currency", sa.Numeric(18, 2), nullable=True),
        sa.Column(
            "purchase_transaction_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("transactions.id"),
            nullable=True,
        ),
        sa.Column("sold_at", sa.Date(), nullable=True),
        sa.Column("sale_price", sa.Numeric(18, 2), nullable=True),
        sa.Column("sale_price_base_currency", sa.Numeric(18, 2), nullable=True),
        sa.Column(
            "sale_transaction_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("transactions.id"),
            nullable=True,
        ),
        sa.Column("vehicle_type", sa.String(12), nullable=True),
        sa.Column("depreciation_rate", sa.Numeric(5, 4), nullable=True),
        sa.Column("metal", sa.String(10), nullable=True),
        sa.Column("metal_form", sa.String(10), nullable=True),
        sa.Column("weight_grams", sa.Numeric(12, 4), nullable=True),
        sa.Column("purity", sa.Numeric(5, 4), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind in ('vehicle','metal')", name="ck_physical_assets_kind"),
        sa.CheckConstraint(
            "(kind = 'vehicle' AND vehicle_type IN ('car','motorcycle','other')"
            " AND depreciation_rate IS NOT NULL AND purchase_price IS NOT NULL"
            " AND metal IS NULL AND metal_form IS NULL"
            " AND weight_grams IS NULL AND purity IS NULL)"
            " OR "
            "(kind = 'metal' AND metal IN ('gold','silver','platinum')"
            " AND metal_form IN ('bullion','coin','jewelry')"
            " AND weight_grams IS NOT NULL AND purity IS NOT NULL"
            " AND vehicle_type IS NULL AND depreciation_rate IS NULL)",
            name="ck_physical_assets_kind_fields",
        ),
        sa.CheckConstraint(
            "depreciation_rate IS NULL OR (depreciation_rate >= 0 AND depreciation_rate < 1)",
            name="ck_physical_assets_depreciation_rate",
        ),
        sa.CheckConstraint(
            "purity IS NULL OR (purity > 0 AND purity <= 1)", name="ck_physical_assets_purity"
        ),
        sa.CheckConstraint(
            "weight_grams IS NULL OR weight_grams > 0", name="ck_physical_assets_weight"
        ),
        sa.CheckConstraint(
            "(sold_at IS NULL) = (sale_price IS NULL)", name="ck_physical_assets_sale"
        ),
    )
    op.create_index("ix_physical_assets_user_id", "physical_assets", ["user_id"])

    op.create_table(
        "physical_asset_valuations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "physical_asset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("physical_assets.id"),
            nullable=False,
        ),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(18, 2), nullable=False),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("value >= 0", name="ck_physical_asset_valuations_value"),
    )
    op.create_index(
        "ix_physical_asset_valuations_physical_asset_id",
        "physical_asset_valuations",
        ["physical_asset_id"],
    )
    op.create_index(
        "uq_physical_asset_valuations_asset_date",
        "physical_asset_valuations",
        ["physical_asset_id", "date"],
        unique=True,
        postgresql_where=sa_text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("physical_asset_valuations")
    op.drop_table("physical_assets")
    op.execute(
        "DELETE FROM asset_prices WHERE asset_id IN "
        "(SELECT id FROM assets WHERE asset_type = 'metal')"
    )
    op.execute("DELETE FROM assets WHERE asset_type = 'metal'")
    op.drop_constraint("ck_assets_type", "assets", type_="check")
    op.create_check_constraint(
        "ck_assets_type", "assets", "asset_type in ('stock','etf','crypto')"
    )

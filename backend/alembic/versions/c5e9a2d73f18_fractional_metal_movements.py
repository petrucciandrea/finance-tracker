"""fractional metal positions: buy/sell movements in grams

Revision ID: c5e9a2d73f18
Revises: b8d2f4a61c97
Create Date: 2026-10-08 12:00:00.000000

A metal row becomes a position whose weight, cost and sales live in
`physical_asset_movements`, so it can be bought into and sold from by the
gram. Each existing metal row is carried over as one buy (its weight, price
and cash leg) plus, if it was sold, one sell of the whole weight; its own
purchase/sale columns are then cleared and `weight_grams` dropped.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c5e9a2d73f18'
down_revision: str | Sequence[str] | None = 'b8d2f4a61c97'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_KIND_FIELDS_CHECK = (
    "(kind = 'vehicle' AND vehicle_type IN ('car','motorcycle','other')"
    " AND depreciation_rate IS NOT NULL"
    " AND purchase_date IS NOT NULL AND purchase_price IS NOT NULL"
    " AND metal IS NULL AND metal_form IS NULL AND purity IS NULL)"
    " OR "
    "(kind = 'metal' AND metal IN ('gold','silver','platinum')"
    " AND metal_form IN ('bullion','coin','jewelry') AND purity IS NOT NULL"
    " AND vehicle_type IS NULL AND depreciation_rate IS NULL"
    " AND purchase_date IS NULL AND purchase_price IS NULL"
    " AND purchase_price_base_currency IS NULL AND purchase_transaction_id IS NULL"
    " AND sold_at IS NULL AND sale_transaction_id IS NULL)"
)

OLD_KIND_FIELDS_CHECK = (
    "(kind = 'vehicle' AND vehicle_type IN ('car','motorcycle','other')"
    " AND depreciation_rate IS NOT NULL AND purchase_price IS NOT NULL"
    " AND metal IS NULL AND metal_form IS NULL"
    " AND weight_grams IS NULL AND purity IS NULL)"
    " OR "
    "(kind = 'metal' AND metal IN ('gold','silver','platinum')"
    " AND metal_form IN ('bullion','coin','jewelry')"
    " AND weight_grams IS NOT NULL AND purity IS NOT NULL"
    " AND vehicle_type IS NULL AND depreciation_rate IS NULL)"
)


def upgrade() -> None:
    op.create_table(
        "physical_asset_movements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "physical_asset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("physical_assets.id"),
            nullable=False,
        ),
        sa.Column("type", sa.String(4), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("weight_grams", sa.Numeric(12, 4), nullable=False),
        sa.Column("price", sa.Numeric(18, 2), nullable=True),
        sa.Column("price_base_currency", sa.Numeric(18, 2), nullable=True),
        sa.Column(
            "transaction_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("transactions.id"),
            nullable=True,
        ),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("type in ('buy','sell')", name="ck_physical_asset_movements_type"),
        sa.CheckConstraint("weight_grams > 0", name="ck_physical_asset_movements_weight"),
        sa.CheckConstraint(
            "price IS NULL OR price >= 0", name="ck_physical_asset_movements_price"
        ),
        sa.CheckConstraint(
            "type = 'buy' OR price IS NOT NULL", name="ck_physical_asset_movements_sale_price"
        ),
    )
    op.create_index(
        "ix_physical_asset_movements_physical_asset_id",
        "physical_asset_movements",
        ["physical_asset_id"],
    )

    # Soft-deleted metal rows are carried over too, so their retired cash
    # legs keep pointing at something.
    op.execute(
        """
        INSERT INTO physical_asset_movements
            (id, physical_asset_id, type, date, weight_grams, price,
             price_base_currency, transaction_id, created_at, deleted_at)
        SELECT gen_random_uuid(), id, 'buy', purchase_date, weight_grams, purchase_price,
               purchase_price_base_currency, purchase_transaction_id, created_at, deleted_at
        FROM physical_assets WHERE kind = 'metal'
        """
    )
    op.execute(
        """
        INSERT INTO physical_asset_movements
            (id, physical_asset_id, type, date, weight_grams, price,
             price_base_currency, transaction_id, created_at, deleted_at)
        SELECT gen_random_uuid(), id, 'sell', sold_at, weight_grams, sale_price,
               sale_price_base_currency, sale_transaction_id, created_at, deleted_at
        FROM physical_assets WHERE kind = 'metal' AND sold_at IS NOT NULL
        """
    )

    op.drop_constraint("ck_physical_assets_kind_fields", "physical_assets", type_="check")
    op.drop_constraint("ck_physical_assets_weight", "physical_assets", type_="check")
    op.alter_column("physical_assets", "purchase_date", nullable=True)
    op.execute(
        """
        UPDATE physical_assets SET
            purchase_date = NULL, purchase_price = NULL,
            purchase_price_base_currency = NULL, purchase_transaction_id = NULL,
            sold_at = NULL, sale_price = NULL,
            sale_price_base_currency = NULL, sale_transaction_id = NULL
        WHERE kind = 'metal'
        """
    )
    op.drop_column("physical_assets", "weight_grams")
    op.create_check_constraint(
        "ck_physical_assets_kind_fields", "physical_assets", NEW_KIND_FIELDS_CHECK
    )


def downgrade() -> None:
    # Only a position that is still one object (a single buy, optionally
    # sold whole) fits back on the row; anything else would lose movements,
    # so refuse rather than collapse them.
    bind = op.get_bind()
    fractional = bind.execute(
        sa.text(
            """
            SELECT count(*) FROM (
                SELECT physical_asset_id FROM physical_asset_movements
                WHERE deleted_at IS NULL
                GROUP BY physical_asset_id
                HAVING count(*) FILTER (WHERE type = 'buy') <> 1
                    OR count(*) FILTER (WHERE type = 'sell') > 1
                    OR sum(CASE WHEN type = 'sell' THEN weight_grams ELSE 0 END) NOT IN
                       (0, sum(CASE WHEN type = 'buy' THEN weight_grams ELSE 0 END))
            ) AS f
            """
        )
    ).scalar()
    if fractional:
        raise RuntimeError(
            f"{fractional} metal position(s) have partial movements and can't be downgraded"
        )

    op.drop_constraint("ck_physical_assets_kind_fields", "physical_assets", type_="check")
    op.add_column("physical_assets", sa.Column("weight_grams", sa.Numeric(12, 4), nullable=True))
    op.execute(
        """
        UPDATE physical_assets a SET
            weight_grams = m.weight_grams, purchase_date = m.date, purchase_price = m.price,
            purchase_price_base_currency = m.price_base_currency,
            purchase_transaction_id = m.transaction_id
        FROM physical_asset_movements m
        WHERE m.physical_asset_id = a.id AND m.type = 'buy' AND m.deleted_at IS NULL
        """
    )
    op.execute(
        """
        UPDATE physical_assets a SET
            sold_at = m.date, sale_price = m.price,
            sale_price_base_currency = m.price_base_currency,
            sale_transaction_id = m.transaction_id
        FROM physical_asset_movements m
        WHERE m.physical_asset_id = a.id AND m.type = 'sell' AND m.deleted_at IS NULL
        """
    )
    # Metal rows whose movements were all soft-deleted (deleted assets) get
    # placeholder values just to satisfy the old CHECK.
    op.execute(
        """
        UPDATE physical_assets SET weight_grams = 1, purchase_date = created_at::date
        WHERE kind = 'metal' AND weight_grams IS NULL
        """
    )
    op.alter_column("physical_assets", "purchase_date", nullable=False)
    op.create_check_constraint(
        "ck_physical_assets_weight", "physical_assets", "weight_grams IS NULL OR weight_grams > 0"
    )
    op.create_check_constraint(
        "ck_physical_assets_kind_fields", "physical_assets", OLD_KIND_FIELDS_CHECK
    )
    op.drop_table("physical_asset_movements")

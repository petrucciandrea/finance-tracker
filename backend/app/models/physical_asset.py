"""
Physical assets: vehicles and precious metals.

Unlike a portfolio holding these aren't a ledger of buys and sells — one
row is one object (a car, a bar, a ring), bought once and sold at most
once. Their value is *estimated*, not quoted: a vehicle depreciates along a
curve the user can re-anchor with a manual valuation, a metal object is
weighed at today's spot price for its fine content.

Both kinds share one table: the net-worth view, the history chart and the
cash legs treat them identically, and only the valuation differs. The
CHECK constraints keep each kind's columns from leaking into the other.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Numeric, String, and_, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base, SoftDeleteMixin, TimestampMixin, uuid_pk

if TYPE_CHECKING:
    from app.models import Transaction


class PhysicalAsset(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "physical_assets"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(10), nullable=False)  # vehicle/metal
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), ForeignKey("currencies.code"), nullable=False)

    purchase_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Nullable for metals only: an inherited ring has no cost, and making one
    # up would invent a P&L. A vehicle's price is its depreciation anchor.
    purchase_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    # Frozen at write time, same rule as Transaction.amount_base_currency.
    purchase_price_base_currency: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2), nullable=True
    )
    # The optional `transfer` row that paid for it. Kept in sync by
    # routers/physical_assets.py, never set by a client directly.
    purchase_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("transactions.id"), nullable=True
    )

    sold_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    sale_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    sale_price_base_currency: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    sale_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("transactions.id"), nullable=True
    )

    # vehicle only
    vehicle_type: Mapped[str | None] = mapped_column(String(12), nullable=True)
    depreciation_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)

    # metal only
    metal: Mapped[str | None] = mapped_column(String(10), nullable=True)
    metal_form: Mapped[str | None] = mapped_column(String(10), nullable=True)
    weight_grams: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    purity: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)

    purchase_transaction: Mapped["Transaction | None"] = relationship(
        foreign_keys=[purchase_transaction_id]
    )
    sale_transaction: Mapped["Transaction | None"] = relationship(
        foreign_keys=[sale_transaction_id]
    )
    # Soft-deleted valuations filtered in the join itself, so no caller can
    # forget to: a deleted valuation re-anchoring the curve would be invisible
    # in the UI and still move the number.
    valuations: Mapped[list["PhysicalAssetValuation"]] = relationship(
        primaryjoin=lambda: and_(
            PhysicalAsset.id == PhysicalAssetValuation.physical_asset_id,
            PhysicalAssetValuation.deleted_at.is_(None),
        ),
        order_by=lambda: PhysicalAssetValuation.date,
        viewonly=True,
        lazy="selectin",
    )

    __table_args__ = (
        CheckConstraint("kind in ('vehicle','metal')", name="ck_physical_assets_kind"),
        CheckConstraint(
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
        CheckConstraint(
            "depreciation_rate IS NULL OR (depreciation_rate >= 0 AND depreciation_rate < 1)",
            name="ck_physical_assets_depreciation_rate",
        ),
        CheckConstraint(
            "purity IS NULL OR (purity > 0 AND purity <= 1)", name="ck_physical_assets_purity"
        ),
        CheckConstraint(
            "weight_grams IS NULL OR weight_grams > 0", name="ck_physical_assets_weight"
        ),
        CheckConstraint(
            "(sold_at IS NULL) = (sale_price IS NULL)", name="ck_physical_assets_sale"
        ),
    )


class PhysicalAssetValuation(Base, TimestampMixin, SoftDeleteMixin):
    """
    A manual appraisal of a vehicle (a dealer quote, a listing price). It
    replaces the purchase price as the depreciation anchor from its date on,
    so the curve bends to reality instead of drifting from it for years.
    """

    __tablename__ = "physical_asset_valuations"

    id: Mapped[uuid.UUID] = uuid_pk()
    physical_asset_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("physical_assets.id"), nullable=False, index=True
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)  # in asset currency
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    __table_args__ = (
        CheckConstraint("value >= 0", name="ck_physical_asset_valuations_value"),
        # Two anchors on the same day would make "the latest one" ambiguous.
        Index(
            "uq_physical_asset_valuations_asset_date",
            "physical_asset_id",
            "date",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

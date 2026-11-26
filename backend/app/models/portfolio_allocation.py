"""
What a product is made of, as the user sees it: asset class, region, sector,
currency.

Per user, never on `assets`: that table is shared by every user, so a
column there would let one person's edit rewrite another's portfolio
analysis (the same reason the demo seed never invents prices). These rows
only *override*: a product without them falls back to the reference file
(`app/data/asset_exposures.json`), then to what its type implies.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base, TimestampMixin, uuid_pk


class AssetExposure(Base, TimestampMixin):
    """
    One bucket's weight in one dimension. A dimension's rows are replaced
    together (PUT), never edited one by one: their sum is what matters, and
    a cross-row sum can't be a CHECK, so the router enforces ≤ 100 on the
    whole set. Configuration, not history: replaced rows are deleted.
    """

    __tablename__ = "asset_exposures"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("assets.id"), nullable=False
    )
    dimension: Mapped[str] = mapped_column(String(12), nullable=False)
    bucket: Mapped[str] = mapped_column(String(30), nullable=False)
    weight: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "user_id", "asset_id", "dimension", "bucket", name="uq_asset_exposures_bucket"
        ),
        CheckConstraint(
            "dimension in ('asset_class','region','sector','currency')",
            name="ck_asset_exposures_dimension",
        ),
        CheckConstraint("weight > 0 AND weight <= 100", name="ck_asset_exposures_weight"),
    )


class AssetProfile(Base, TimestampMixin):
    """When the user's weights were taken (the factsheet's date) and a note."""

    __tablename__ = "asset_profiles"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("assets.id"), nullable=False
    )
    as_of: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    __table_args__ = (UniqueConstraint("user_id", "asset_id", name="uq_asset_profiles_asset"),)


class PortfolioRule(Base, TimestampMixin):
    """
    A guardrail on pillar 4, set by the user (a preset only fills the
    targets in; nothing is preset as a cap):

    - `target`: `bucket` of `dimension` (asset class or region) at
      `target_pct` ± `tolerance_pct` points.
    - `max_share`: `bucket` of `dimension` at most `max_pct`; with dimension
      `position`, `bucket` is an asset id and the cap is on that one product.
    - `excess_cash`: idle cash above `threshold_amount`, or above
      `threshold_months` of average spend.
    - `min_invested`: invested at least `min_pct` of the free financial wealth.

    One table rather than four: they are listed, evaluated and alerted on
    together, and each kind's columns are kept apart by the CHECK below.
    """

    __tablename__ = "portfolio_rules"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    dimension: Mapped[str | None] = mapped_column(String(12), nullable=True)
    bucket: Mapped[str | None] = mapped_column(String(40), nullable=True)
    target_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    tolerance_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    max_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    min_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    threshold_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    threshold_months: Mapped[Decimal | None] = mapped_column(Numeric(4, 1), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "kind in ('target','max_share','excess_cash','min_invested')",
            name="ck_portfolio_rules_kind",
        ),
        CheckConstraint(
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

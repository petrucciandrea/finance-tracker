"""
Asset buy/sell ledger (phase 3 — portfolio tracker).

Replaces the old `Holding` model (a single manually-entered quantity +
avg_buy_price row per account+asset, no history). A holding is now a
*computed* aggregate over these rows (see `routers/portfolio.py`), the same
way an account balance is computed from `Transaction` rows rather than
stored — so this gets `SoftDeleteMixin` like `Transaction`, unlike the old
`Holding` which was hard-deleted as "a live position, not a historical
event". Once buys/sells are the source of truth, a row IS the historical
event.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base, SoftDeleteMixin, TimestampMixin, uuid_pk

if TYPE_CHECKING:
    from app.models import Account, Asset, Transaction


class AssetTransaction(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "asset_transactions"

    id: Mapped[uuid.UUID] = uuid_pk()
    account_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False, index=True
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("assets.id"), nullable=False, index=True
    )
    # The cash-side counterpart of this buy/sell: a `transfer` Transaction on
    # the same account for the same amount, so the money leaving/entering
    # the account's cash balance is neither invisible (double-counting net
    # worth once the holding's value is added on top) nor miscategorized as
    # an expense/income (which would distort monthly spend reports). Kept in
    # sync by routers/portfolio.py, never set directly by a client.
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("transactions.id"), nullable=True
    )
    type: Mapped[str] = mapped_column(String(4), nullable=False)  # buy/sell
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    # per unit, in asset.currency
    price: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    fee: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, default=0)
    # Frozen at write time, same rule as Transaction.amount_base_currency: never
    # recomputed on read, only when quantity/price/fee/date change on PATCH.
    amount_base_currency: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    account: Mapped["Account"] = relationship(back_populates="asset_transactions")
    asset: Mapped["Asset"] = relationship(back_populates="asset_transactions")
    transaction: Mapped["Transaction | None"] = relationship()

    __table_args__ = (
        CheckConstraint("type in ('buy','sell')", name="ck_asset_transactions_type"),
    )

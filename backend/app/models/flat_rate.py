"""
P.IVA in regime forfettario: invoices, F24 payments, per-year fiscal
parameters and the accounts/holdings the tax provision is parked in.

Taxes accrue on what is *collected*, not on what is invoiced (principio di
cassa): every figure in `services/flat_rate.py` filters on
`invoices.collected_on`, so an invoice issued in December and paid in
January lands in January's year.

The fiscal parameters live per year and are frozen once the year exists,
for the same reason exchange rates are frozen on transactions: the 5%
start-up rate only lasts five years and the INPS rate changes every year,
and editing next year's numbers must not rewrite last year's liability.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    false,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base, SoftDeleteMixin, TimestampMixin, uuid_pk

if TYPE_CHECKING:
    from app.models import Account, Asset, Transaction


class FlatRateSettings(Base, TimestampMixin):
    """What isn't per year: when the activity started and how much buffer
    the suggested provision rate adds on top of the computed need."""

    __tablename__ = "flat_rate_settings"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, unique=True
    )
    # Drives the first-year suggestion (no advances paid yet) and the
    # annualisation of a partial first year (advances computed on 7 months).
    activity_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    safety_margin: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), nullable=False, default=Decimal("0.15"), server_default="0.15"
    )

    __table_args__ = (
        CheckConstraint(
            "safety_margin >= 0 AND safety_margin <= 1", name="ck_flat_rate_settings_margin"
        ),
    )


class FlatRateYear(Base, TimestampMixin):
    """
    One fiscal year's parameters. Created on first use by copying the
    previous year (or the module defaults), then edited by the user.

    Unique on (user, year), unlike `allocation_plans`: a duplicate row here
    would make the year's numbers depend on which one a query happens to
    pick. The get-or-create uses INSERT ... ON CONFLICT DO NOTHING, so two
    concurrent first reads still can't 500.
    """

    __tablename__ = "flat_rate_years"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    profitability_coefficient: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    # NULL = automatic: 5% for the start year and the four after it, 15%
    # after that (services/flat_rate.py:automatic_tax_rate). A value is an
    # override, for someone who doesn't meet the 5%'s other conditions.
    substitute_tax_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    inps_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    # Rivalsa INPS 4% (gestione separata): charged to the client on top of
    # the fee, and part of revenue — unlike a cassa's contributo integrativo.
    rivalsa_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    # NULL = use the suggested rate. A suggestion moves with the data; an
    # explicit choice doesn't.
    provision_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)

    __table_args__ = (
        Index("uq_flat_rate_years_user_year", "user_id", "year", unique=True),
        CheckConstraint(
            "profitability_coefficient > 0 AND profitability_coefficient <= 1"
            " AND (substitute_tax_rate IS NULL"
            " OR (substitute_tax_rate >= 0 AND substitute_tax_rate < 1))"
            " AND inps_rate >= 0 AND inps_rate < 1"
            " AND rivalsa_rate >= 0 AND rivalsa_rate < 1"
            " AND (provision_rate IS NULL OR (provision_rate >= 0 AND provision_rate <= 1))",
            name="ck_flat_rate_years_rates",
        ),
    )


class Invoice(Base, TimestampMixin, SoftDeleteMixin):
    """
    An issued invoice, in EUR (the regime is Italian). The fee is stored;
    rivalsa, bollo and total are derived. `rivalsa_rate` is frozen at
    creation so a later change of the year's default doesn't re-price it.
    """

    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    client: Mapped[str] = mapped_column(String(200), nullable=False)
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    rivalsa_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    # €2 bollo charged to the client — revenue too (AdE, risposta 428/2022).
    stamp_duty: Mapped[bool] = mapped_column(Boolean, nullable=False)
    collected_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Per-invoice override of the year's provision rate.
    provision_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # The income movement that collected it: either linked (typically
    # imported from CSV) or written from here. Only one written from here is
    # retired when the collection is undone — a linked one belongs to the
    # bank statement.
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("transactions.id"), nullable=True
    )
    owns_transaction: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )

    transaction: Mapped["Transaction | None"] = relationship()

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_invoices_amount"),
        CheckConstraint("rivalsa_rate >= 0 AND rivalsa_rate < 1", name="ck_invoices_rivalsa"),
        CheckConstraint(
            "provision_rate IS NULL OR (provision_rate >= 0 AND provision_rate <= 1)",
            name="ck_invoices_provision_rate",
        ),
        CheckConstraint(
            "transaction_id IS NULL OR collected_on IS NOT NULL",
            name="ck_invoices_transaction_needs_collection",
        ),
        CheckConstraint(
            "NOT owns_transaction OR transaction_id IS NOT NULL",
            name="ck_invoices_owned_transaction",
        ),
        # One bank movement settles one invoice.
        Index(
            "uq_invoices_transaction",
            "transaction_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND transaction_id IS NOT NULL"),
        ),
    )


class TaxPayment(Base, TimestampMixin, SoftDeleteMixin):
    """
    One F24 line: a saldo or an acconto of either the imposta sostitutiva
    or the INPS contributions, for a given fiscal year. Paying from an
    account writes a one-sided `transfer`, not an expense: the cost was
    already booked as a liability when the income came in, and paying it
    only swaps cash for a smaller debt.
    """

    __tablename__ = "tax_payments"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    paid_on: Mapped[date] = mapped_column(Date, nullable=False)
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    component: Mapped[str] = mapped_column(String(20), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("transactions.id"), nullable=True
    )

    transaction: Mapped["Transaction | None"] = relationship()

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_tax_payments_amount"),
        CheckConstraint(
            "component in ('substitute_tax','inps')", name="ck_tax_payments_component"
        ),
        CheckConstraint(
            "kind in ('balance','first_advance','second_advance')", name="ck_tax_payments_kind"
        ),
    )


class FlatRateProvisionSource(Base, TimestampMixin, SoftDeleteMixin):
    """
    Where the tax provision is parked. `(account)` counts the account's
    cash; `(account, asset)` counts that holding inside the account — the
    (account, asset) grain `SavingsGoalSource` named for asset-backed rungs.
    A broker holding an ETF plus its uninvested cash is two rows.

    Earmarked money: an account source can't fund a savings goal, and its
    balance stays out of the survival budget's runway.
    """

    __tablename__ = "flat_rate_provision_sources"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False
    )
    asset_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("assets.id"), nullable=True
    )

    account: Mapped["Account"] = relationship()
    asset: Mapped["Asset | None"] = relationship()

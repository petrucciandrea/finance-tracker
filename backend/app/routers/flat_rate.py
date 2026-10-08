"""
P.IVA forfettaria: invoices (issued → collected), F24 payments, the
per-year fiscal parameters and the accounts/holdings the provision sits in.
The arithmetic lives in `services/flat_rate.py`; this router keeps the
rows, and the movements on accounts they own, consistent.

Nothing here checks `users.work_type`: the profile toggle only hides the
section. Switching it off must not make a real tax debt vanish from net
worth, so the data and the endpoints keep working regardless.
"""

from datetime import UTC, datetime, timedelta
from datetime import date as date_
from decimal import Decimal
from enum import Enum
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.models import (
    Account,
    Asset,
    FlatRateProvisionSource,
    FlatRateYear,
    Invoice,
    SavingsGoal,
    SavingsGoalSource,
    TaxPayment,
    Transaction,
    User,
)
from app.schemas import (
    F24Deadline,
    FlatRateSettingsUpdate,
    FlatRateSummary,
    FlatRateYearFigures,
    FlatRateYearUpdate,
    InvoiceCollect,
    InvoiceCreate,
    InvoiceStatus,
    InvoiceUpdate,
    ProvisionSourceCreate,
    ProvisionStatus,
    TaxComponent,
    TaxPaymentCreate,
    TaxPaymentKind,
    TaxPaymentUpdate,
)
from app.schemas import FlatRateSettings as FlatRateSettingsSchema
from app.schemas import FlatRateYear as FlatRateYearSchema
from app.schemas import Invoice as InvoiceSchema
from app.schemas import TaxPayment as TaxPaymentSchema
from app.schemas import Transaction as TransactionSchema
from app.services import flat_rate as service
from app.services.exchange_rates import ExchangeRateUnavailable, get_rate
from app.services.net_worth import compute_holding_positions
from app.services.ownership import (
    ensure_account_open_on,
    get_or_create_misc_category,
    get_owned_account,
    get_owned_leaf_category,
)
from app.services.transfers import create_cash_leg

router = APIRouter(prefix="/api/v1/flat-rate", tags=["flat-rate"])

_TAX_LABELS = {"substitute_tax": "imposta sostitutiva", "inps": "INPS"}
_KIND_LABELS = {
    "balance": "saldo",
    "first_advance": "1° acconto",
    "second_advance": "2° acconto",
}
# How far from the issue date an income movement may be to be offered as
# the one that collected the invoice: a little before (an advance), up to
# half a year after (slow payers).
_CANDIDATE_WINDOW = (timedelta(days=30), timedelta(days=180))
# Bank fees can shave a little off a wire.
_CANDIDATE_TOLERANCE = Decimal("1.00")


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)


def _rate(db: Session, user: User, on_date: date_) -> Decimal:
    try:
        return get_rate(db, service.CURRENCY, user.base_currency, on_date)
    except ExchangeRateUnavailable as exc:
        raise _unprocessable(str(exc)) from exc


def _get_owned_invoice(db: Session, invoice_id: UUID, user: User) -> Invoice:
    invoice = (
        db.query(Invoice)
        .filter(
            Invoice.id == invoice_id,
            Invoice.user_id == user.id,
            Invoice.deleted_at.is_(None),
        )
        .first()
    )
    if invoice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")
    return invoice


def _get_owned_payment(db: Session, payment_id: UUID, user: User) -> TaxPayment:
    payment = (
        db.query(TaxPayment)
        .filter(
            TaxPayment.id == payment_id,
            TaxPayment.user_id == user.id,
            TaxPayment.deleted_at.is_(None),
        )
        .first()
    )
    if payment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")
    return payment


def _eur_account(db: Session, user: User, account_id: UUID) -> Account:
    account = get_owned_account(db, account_id, user)
    # Converting would mean a rate inside a multi-row write, and the
    # movement would no longer match the invoice or the F24 the user has.
    if account.currency != service.CURRENCY:
        raise _unprocessable("The account must be in EUR")
    return account


def _retire_transaction(db: Session, transaction_id: UUID | None) -> None:
    if transaction_id is None:
        return
    transaction = db.get(Transaction, transaction_id)
    if transaction is not None and transaction.deleted_at is None:
        transaction.deleted_at = datetime.now(UTC)


def _year_schema(ledger: service.Ledger, year: int) -> FlatRateYearSchema:
    params = ledger.params_for(year)
    suggestion = service.suggest_provision_rate(ledger, year)
    return FlatRateYearSchema(
        year=year,
        profitability_coefficient=params.profitability_coefficient,
        substitute_tax_rate=params.substitute_tax_rate,
        substitute_tax_rate_is_automatic=params.substitute_tax_rate_is_automatic,
        startup_last_year=service.startup_last_year(ledger.activity_start),
        inps_rate=params.inps_rate,
        rivalsa_rate=params.rivalsa_rate,
        provision_rate=params.provision_rate,
        load_rate=suggestion.load_rate,
        advance_rate=suggestion.advance_rate,
        needed_rate=suggestion.needed_rate,
        suggested_provision_rate=suggestion.suggested_rate,
        effective_provision_rate=(
            params.provision_rate
            if params.provision_rate is not None
            else suggestion.suggested_rate
        ),
    )


class _InvoiceView:
    """Serialises invoices against one ledger, computing each year's rate once."""

    def __init__(self, ledger: service.Ledger) -> None:
        self.ledger = ledger
        self._rates: dict[int, Decimal] = {}

    def year_rate(self, year: int) -> Decimal:
        if year not in self._rates:
            self._rates[year] = service.effective_provision_rate(self.ledger, year)
        return self._rates[year]

    def __call__(self, invoice: Invoice) -> InvoiceSchema:
        year = service.fiscal_year_of(invoice)
        breakdown = service.invoice_breakdown(
            invoice, self.ledger.params_for(year), self.year_rate(year)
        )
        transaction = invoice.transaction
        return InvoiceSchema(
            id=invoice.id,
            number=invoice.number,
            client=invoice.client,
            issue_date=invoice.issue_date,
            collected_on=invoice.collected_on,
            amount=invoice.amount,
            rivalsa_rate=invoice.rivalsa_rate,
            rivalsa_amount=breakdown.rivalsa_amount,
            stamp_duty=invoice.stamp_duty,
            stamp_duty_amount=breakdown.stamp_duty_amount,
            total=breakdown.total,
            fiscal_year=year,
            provision_rate=invoice.provision_rate,
            applied_provision_rate=breakdown.applied_provision_rate,
            taxable_base=breakdown.taxable_base,
            substitute_tax=breakdown.substitute_tax,
            inps=breakdown.inps,
            substitute_tax_advance=breakdown.substitute_tax_advance,
            inps_advance=breakdown.inps_advance,
            to_provision=breakdown.to_provision,
            transaction_id=invoice.transaction_id,
            owns_transaction=invoice.owns_transaction,
            transaction_account_id=transaction.account_id if transaction else None,
            transaction_deleted=bool(transaction and transaction.deleted_at is not None),
            notes=invoice.notes,
            created_at=invoice.created_at,
        )


def _invoice_response(db: Session, user: User, invoice: Invoice) -> InvoiceSchema:
    db.refresh(invoice)
    return _InvoiceView(service.load_ledger(db, user))(invoice)


def _payment_schema(payment: TaxPayment) -> TaxPaymentSchema:
    leg = payment.transaction
    return TaxPaymentSchema(
        id=payment.id,
        paid_on=payment.paid_on,
        fiscal_year=payment.fiscal_year,
        component=TaxComponent(payment.component),
        kind=TaxPaymentKind(payment.kind),
        amount=payment.amount,
        notes=payment.notes,
        transaction_id=payment.transaction_id,
        account_id=leg.account_id if leg is not None and leg.deleted_at is None else None,
        created_at=payment.created_at,
    )


# ---------------------------------------------------------------------------
# Settings and per-year parameters
# ---------------------------------------------------------------------------

@router.get("/settings", response_model=FlatRateSettingsSchema)
def get_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FlatRateSettingsSchema:
    settings = service.get_or_create_settings(db, current_user)
    db.commit()
    return FlatRateSettingsSchema.model_validate(settings)


@router.patch("/settings", response_model=FlatRateSettingsSchema)
def update_settings(
    payload: FlatRateSettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FlatRateSettingsSchema:
    settings = service.get_or_create_settings(db, current_user)
    data = payload.model_dump(exclude_unset=True)
    if "activity_start_date" in data:
        settings.activity_start_date = data["activity_start_date"]
    if data.get("safety_margin") is not None:
        settings.safety_margin = data["safety_margin"]
    db.commit()
    db.refresh(settings)
    return FlatRateSettingsSchema.model_validate(settings)


@router.get("/years/{year}", response_model=FlatRateYearSchema)
def get_year(
    year: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FlatRateYearSchema:
    _check_year(year)
    service.get_or_create_year(db, current_user, year)
    db.commit()
    return _year_schema(service.load_ledger(db, current_user), year)


@router.patch("/years/{year}", response_model=FlatRateYearSchema)
def update_year(
    year: int,
    payload: FlatRateYearUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FlatRateYearSchema:
    _check_year(year)
    row: FlatRateYear = service.get_or_create_year(db, current_user, year)
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        # null puts these two back on automatic / the suggestion.
        if value is None and field not in ("provision_rate", "substitute_tax_rate"):
            raise _unprocessable(f"{field} can't be cleared")
        setattr(row, field, value)
    db.commit()
    return _year_schema(service.load_ledger(db, current_user), year)


def _check_year(year: int) -> None:
    if not 2000 <= year <= 2100:
        raise _unprocessable("Year out of range")


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------

@router.get("/invoices", response_model=list[InvoiceSchema])
def list_invoices(
    year: int | None = None,
    status_filter: Annotated[InvoiceStatus | None, Query(alias="status")] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[InvoiceSchema]:
    """
    `year` matches an invoice issued *or* collected in it: a December
    invoice paid in January belongs to both years' lists — issued in one,
    taxed in the other.
    """
    query = db.query(Invoice).filter(
        Invoice.user_id == current_user.id, Invoice.deleted_at.is_(None)
    )
    if year is not None:
        query = query.filter(
            or_(
                func.extract("year", Invoice.issue_date) == year,
                func.extract("year", Invoice.collected_on) == year,
            )
        )
    if status_filter == InvoiceStatus.collected:
        query = query.filter(Invoice.collected_on.isnot(None))
    elif status_filter == InvoiceStatus.outstanding:
        query = query.filter(Invoice.collected_on.is_(None))
    invoices = query.order_by(Invoice.issue_date.desc(), Invoice.created_at.desc()).all()
    view = _InvoiceView(service.load_ledger(db, current_user))
    return [view(invoice) for invoice in invoices]


@router.get("/clients", response_model=list[str])
def list_clients(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[str]:
    """Every client invoiced so far, most recently invoiced first — for autocomplete."""
    rows = (
        db.query(Invoice.client)
        .filter(Invoice.user_id == current_user.id, Invoice.deleted_at.is_(None))
        .group_by(Invoice.client)
        .order_by(func.max(Invoice.issue_date).desc(), Invoice.client)
        .all()
    )
    return [row._mapping["client"] for row in rows]


@router.post("/invoices", response_model=InvoiceSchema, status_code=status.HTTP_201_CREATED)
def create_invoice(
    payload: InvoiceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InvoiceSchema:
    year = service.get_or_create_year(db, current_user, payload.issue_date.year)
    rivalsa_rate = (
        payload.rivalsa_rate if payload.rivalsa_rate is not None else year.rivalsa_rate
    )
    stamp_duty = (
        payload.stamp_duty
        if payload.stamp_duty is not None
        else service.auto_stamp_duty(payload.amount, Decimal(rivalsa_rate))
    )
    invoice = Invoice(
        user_id=current_user.id,
        number=payload.number,
        client=payload.client,
        issue_date=payload.issue_date,
        amount=payload.amount,
        rivalsa_rate=rivalsa_rate,
        stamp_duty=stamp_duty,
        provision_rate=payload.provision_rate,
        notes=payload.notes,
    )
    db.add(invoice)
    db.commit()
    return _invoice_response(db, current_user, invoice)


@router.patch("/invoices/{invoice_id}", response_model=InvoiceSchema)
def update_invoice(
    invoice_id: UUID,
    payload: InvoiceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InvoiceSchema:
    invoice = _get_owned_invoice(db, invoice_id, current_user)
    data = payload.model_dump(exclude_unset=True)
    for field in ("client", "issue_date", "amount", "rivalsa_rate", "stamp_duty"):
        if field in data and data[field] is None:
            raise _unprocessable(f"{field} can't be cleared")

    if "collected_on" in data:
        if data["collected_on"] is None:
            raise _unprocessable("Undo the collection instead of clearing its date")
        if invoice.collected_on is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Not collected — mark it collected first",
            )

    old_total = service.invoice_total(invoice)
    leg = invoice.transaction if invoice.owns_transaction else None
    if leg is not None and leg.deleted_at is not None:
        leg = None
    leg_date = data.get("collected_on") or (leg.date if leg is not None else None)
    redating = leg is not None and leg_date != leg.date
    if redating and leg is not None and leg_date is not None:
        ensure_account_open_on(leg.account, leg_date)
    # Resolved before touching any row: see CLAUDE.md, "resolve every rate
    # before the first write". A new date reconverts, as any transaction's does.
    rate = _rate(db, current_user, leg_date) if leg_date is not None and leg is not None else None
    if "issue_date" in data:
        service.get_or_create_year(db, current_user, data["issue_date"].year)
    if data.get("collected_on") is not None:
        # The year it's taxed in may change with it.
        service.get_or_create_year(db, current_user, data["collected_on"].year)

    for field, value in data.items():
        setattr(invoice, field, value)

    new_total = service.invoice_total(invoice)
    # The movement written by collecting is the invoice's own: it follows
    # the total and the collection date. A linked one is the bank's record
    # and stays as it is.
    if (
        leg is not None
        and rate is not None
        and leg_date is not None
        and (new_total != old_total or redating)
    ):
        leg.amount = new_total
        leg.amount_base_currency = new_total * rate
        leg.exchange_rate = rate
        leg.date = leg_date
    db.commit()
    return _invoice_response(db, current_user, invoice)


@router.delete("/invoices/{invoice_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_invoice(
    invoice_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    invoice = _get_owned_invoice(db, invoice_id, current_user)
    if invoice.owns_transaction:
        _retire_transaction(db, invoice.transaction_id)
    invoice.deleted_at = datetime.now(UTC)
    db.commit()


@router.post("/invoices/{invoice_id}/collect", response_model=InvoiceSchema)
def collect_invoice(
    invoice_id: UUID,
    payload: InvoiceCollect,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InvoiceSchema:
    invoice = _get_owned_invoice(db, invoice_id, current_user)
    if invoice.collected_on is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already collected")
    if payload.transaction_id is not None and payload.account_id is not None:
        raise _unprocessable("Link an existing movement or create one, not both")
    if payload.category_id is not None and payload.account_id is None:
        raise _unprocessable("A category only applies to a movement created on an account")

    transaction: Transaction | None = None
    owns_transaction = False
    if payload.transaction_id is not None:
        transaction = _linkable_transaction(db, current_user, payload.transaction_id)
    elif payload.account_id is not None:
        account = _eur_account(db, current_user, payload.account_id)
        ensure_account_open_on(account, payload.collected_on)
        category_id = (
            get_owned_leaf_category(db, payload.category_id, current_user, "income").id
            if payload.category_id is not None
            else None
        )
        rate = _rate(db, current_user, payload.collected_on)
        if category_id is None:
            category_id = get_or_create_misc_category(db, current_user, "income").id
        total = service.invoice_total(invoice)
        label = f"Fattura {invoice.number}" if invoice.number else "Fattura"
        transaction = Transaction(
            account_id=account.id,
            category_id=category_id,
            amount=total,
            currency=service.CURRENCY,
            amount_base_currency=total * rate,
            exchange_rate=rate,
            date=payload.collected_on,
            description=f"{label} — {invoice.client}",
            type="income",
            source="manual",
        )
        db.add(transaction)
        db.flush()
        owns_transaction = True
    # Before the invoice changes: get-or-create queries, and an autoflush of
    # a half-updated invoice would trip its CHECKs.
    service.get_or_create_year(db, current_user, payload.collected_on.year)

    invoice.collected_on = payload.collected_on
    invoice.transaction_id = transaction.id if transaction is not None else None
    invoice.owns_transaction = owns_transaction
    db.commit()
    return _invoice_response(db, current_user, invoice)


def _linkable_transaction(db: Session, user: User, transaction_id: UUID) -> Transaction:
    transaction = (
        db.query(Transaction)
        .join(Account, Account.id == Transaction.account_id)
        .filter(
            Transaction.id == transaction_id,
            Account.user_id == user.id,
            Account.deleted_at.is_(None),
            Transaction.deleted_at.is_(None),
        )
        .first()
    )
    if transaction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    if transaction.type != "income":
        raise _unprocessable("Only an income movement can collect an invoice")
    other = (
        db.query(Invoice)
        .filter(Invoice.transaction_id == transaction.id, Invoice.deleted_at.is_(None))
        .first()
    )
    if other is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This movement already collects the invoice to «{other.client}»",
        )
    return transaction


@router.post("/invoices/{invoice_id}/uncollect", response_model=InvoiceSchema)
def uncollect_invoice(
    invoice_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InvoiceSchema:
    invoice = _get_owned_invoice(db, invoice_id, current_user)
    if invoice.collected_on is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Not collected")
    if invoice.owns_transaction:
        _retire_transaction(db, invoice.transaction_id)
    invoice.transaction_id = None
    invoice.owns_transaction = False
    invoice.collected_on = None
    db.commit()
    return _invoice_response(db, current_user, invoice)


@router.get("/invoices/{invoice_id}/candidates", response_model=list[TransactionSchema])
def collection_candidates(
    invoice_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Transaction]:
    """Income movements that look like this invoice's payment, closest date first."""
    invoice = _get_owned_invoice(db, invoice_id, current_user)
    total = service.invoice_total(invoice)
    before, after = _CANDIDATE_WINDOW
    linked = (
        db.query(Invoice.transaction_id)
        .filter(
            Invoice.user_id == current_user.id,
            Invoice.deleted_at.is_(None),
            Invoice.transaction_id.isnot(None),
        )
        .scalar_subquery()
    )
    candidates = (
        db.query(Transaction)
        .join(Account, Account.id == Transaction.account_id)
        .filter(
            Account.user_id == current_user.id,
            Account.deleted_at.is_(None),
            Transaction.deleted_at.is_(None),
            Transaction.type == "income",
            Transaction.currency == service.CURRENCY,
            func.abs(Transaction.amount - total) <= _CANDIDATE_TOLERANCE,
            Transaction.date >= invoice.issue_date - before,
            Transaction.date <= invoice.issue_date + after,
            Transaction.id.notin_(linked),
        )
        .all()
    )
    candidates.sort(key=lambda t: abs((t.date - invoice.issue_date).days))
    return candidates[:10]


# ---------------------------------------------------------------------------
# F24 payments
# ---------------------------------------------------------------------------

@router.get("/payments", response_model=list[TaxPaymentSchema])
def list_payments(
    year: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[TaxPaymentSchema]:
    """`year` matches the year paid *or* the fiscal year it's for."""
    query = db.query(TaxPayment).filter(
        TaxPayment.user_id == current_user.id, TaxPayment.deleted_at.is_(None)
    )
    if year is not None:
        query = query.filter(
            or_(
                func.extract("year", TaxPayment.paid_on) == year,
                TaxPayment.fiscal_year == year,
            )
        )
    payments = query.order_by(TaxPayment.paid_on.desc(), TaxPayment.created_at.desc()).all()
    return [_payment_schema(p) for p in payments]


@router.post("/payments", response_model=TaxPaymentSchema, status_code=status.HTTP_201_CREATED)
def create_payment(
    payload: TaxPaymentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TaxPaymentSchema:
    if payload.category_id is not None and payload.account_id is None:
        raise _unprocessable("A category only applies to a payment from an account")
    account = (
        _eur_account(db, current_user, payload.account_id)
        if payload.account_id is not None
        else None
    )
    category_id = (
        get_owned_leaf_category(db, payload.category_id, current_user, "transfer").id
        if payload.category_id is not None
        else None
    )
    rate = _rate(db, current_user, payload.paid_on) if account is not None else None
    service.get_or_create_year(db, current_user, payload.fiscal_year)

    leg = None
    if account is not None and rate is not None:
        leg = create_cash_leg(
            db,
            account=account,
            amount=-payload.amount,
            currency=service.CURRENCY,
            rate=rate,
            on_date=payload.paid_on,
            description=_payment_description(
                payload.component.value, payload.kind.value, payload.fiscal_year
            ),
            category_id=category_id,
        )
    payment = TaxPayment(
        user_id=current_user.id,
        paid_on=payload.paid_on,
        fiscal_year=payload.fiscal_year,
        component=payload.component.value,
        kind=payload.kind.value,
        amount=payload.amount,
        notes=payload.notes,
        transaction_id=leg.id if leg is not None else None,
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return _payment_schema(payment)


def _payment_description(component: str, kind: str, fiscal_year: int) -> str:
    return f"F24 {_TAX_LABELS[component]} — {_KIND_LABELS[kind]} {fiscal_year}"


@router.patch("/payments/{payment_id}", response_model=TaxPaymentSchema)
def update_payment(
    payment_id: UUID,
    payload: TaxPaymentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TaxPaymentSchema:
    payment = _get_owned_payment(db, payment_id, current_user)
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        if value is None and field != "notes":
            raise _unprocessable(f"{field} can't be cleared")

    leg = payment.transaction
    if leg is not None and leg.deleted_at is not None:
        leg = None
    moves_leg = leg is not None and bool(data.keys() & {"amount", "paid_on"})
    new_date = data.get("paid_on", payment.paid_on)
    if moves_leg and leg is not None:
        ensure_account_open_on(leg.account, new_date)
    # Frozen-rate rule: reconverted only when amount or date change.
    rate = _rate(db, current_user, new_date) if moves_leg else None
    if "fiscal_year" in data:
        service.get_or_create_year(db, current_user, data["fiscal_year"])

    for field, value in data.items():
        setattr(payment, field, value.value if isinstance(value, Enum) else value)

    if leg is not None:
        if moves_leg and rate is not None:
            leg.amount = -Decimal(payment.amount)
            leg.amount_base_currency = leg.amount * rate
            leg.exchange_rate = rate
            leg.date = payment.paid_on
        leg.description = _payment_description(
            payment.component, payment.kind, payment.fiscal_year
        )
    db.commit()
    db.refresh(payment)
    return _payment_schema(payment)


@router.delete("/payments/{payment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_payment(
    payment_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    payment = _get_owned_payment(db, payment_id, current_user)
    _retire_transaction(db, payment.transaction_id)
    payment.deleted_at = datetime.now(UTC)
    db.commit()


# ---------------------------------------------------------------------------
# Provision sources
# ---------------------------------------------------------------------------

@router.get("/sources", response_model=ProvisionStatus)
def list_sources(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProvisionStatus:
    provision = service.provision_status(db, current_user)
    db.commit()  # persist the price/rate cache rows filled in above
    return provision


@router.post("/sources", response_model=ProvisionStatus, status_code=status.HTTP_201_CREATED)
def add_source(
    payload: ProvisionSourceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProvisionStatus:
    account = get_owned_account(db, payload.account_id, current_user)

    duplicate = (
        db.query(FlatRateProvisionSource)
        .filter(
            FlatRateProvisionSource.user_id == current_user.id,
            FlatRateProvisionSource.deleted_at.is_(None),
            FlatRateProvisionSource.account_id == account.id,
            (
                FlatRateProvisionSource.asset_id == payload.asset_id
                if payload.asset_id is not None
                else FlatRateProvisionSource.asset_id.is_(None)
            ),
        )
        .first()
    )
    if duplicate is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Already part of the provision"
        )

    if payload.asset_id is None:
        # Earmarked cash can't also fund a savings goal, or it would be
        # counted as both the State's money and the user's savings.
        goal = (
            db.query(SavingsGoal)
            .join(SavingsGoalSource, SavingsGoalSource.goal_id == SavingsGoal.id)
            .filter(
                SavingsGoal.user_id == current_user.id,
                SavingsGoal.deleted_at.is_(None),
                SavingsGoalSource.account_id == account.id,
                SavingsGoalSource.deleted_at.is_(None),
            )
            .first()
        )
        if goal is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"This account funds the savings goal «{goal.name}» — "
                "detach it from the goal first",
            )
    else:
        asset = db.get(Asset, payload.asset_id)
        if asset is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
        if (account.id, asset.id) not in compute_holding_positions(db, current_user):
            raise _unprocessable("This account holds no position in that product")

    db.add(
        FlatRateProvisionSource(
            user_id=current_user.id, account_id=account.id, asset_id=payload.asset_id
        )
    )
    db.flush()
    provision = service.provision_status(db, current_user)
    db.commit()
    return provision


@router.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_source(
    source_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    source = (
        db.query(FlatRateProvisionSource)
        .filter(
            FlatRateProvisionSource.id == source_id,
            FlatRateProvisionSource.user_id == current_user.id,
            FlatRateProvisionSource.deleted_at.is_(None),
        )
        .first()
    )
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
    source.deleted_at = datetime.now(UTC)
    db.commit()


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

@router.get("/summary", response_model=FlatRateSummary)
def summary(
    year: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FlatRateSummary:
    today = date_.today()
    year = year if year is not None else today.year
    _check_year(year)
    service.get_or_create_year(db, current_user, year)
    ledger = service.load_ledger(db, current_user)
    as_of = min(today, date_(year, 12, 31))

    figures = service.year_figures(ledger, year, as_of)
    view = _InvoiceView(ledger)
    to_provision = sum(
        (
            view(inv).to_provision
            for inv in ledger.invoices
            if inv.collected_on is not None
            and inv.collected_on.year == year
            and inv.collected_on <= as_of
        ),
        Decimal("0"),
    )
    issued = (
        db.query(Invoice)
        .filter(
            Invoice.user_id == current_user.id,
            Invoice.deleted_at.is_(None),
            func.extract("year", Invoice.issue_date) == year,
        )
        .all()
    )
    outstanding = sum(
        (service.invoice_total(inv) for inv in issued if inv.collected_on is None),
        Decimal("0"),
    )

    liability = service.tax_liability(ledger, today)
    requirement = service.cash_requirement(ledger, today)
    provision = service.provision_status(db, current_user)
    requirement_base = service.liability_in_base_currency(db, current_user, requirement, today)
    db.commit()  # the year row, plus any price/rate cache rows filled in above

    return FlatRateSummary(
        year=year,
        as_of=as_of,
        params=_year_schema(ledger, year),
        figures=FlatRateYearFigures(
            revenue=figures.revenue,
            revenue_limit=service.REVENUE_LIMIT,
            taxable_base=figures.taxable_base,
            inps=figures.inps,
            inps_deducted=figures.inps_deducted,
            substitute_tax=figures.substitute_tax,
            liability=figures.liability,
            advances_due=service.advances_due(ledger, year).total,
            paid=service.paid(ledger, fiscal_year=year),
            to_provision=to_provision,
            outstanding=outstanding,
            invoice_count=len(issued),
        ),
        tax_liability=liability,
        cash_requirement=requirement,
        provision=provision,
        gap=provision.total_base_currency - requirement_base,
        deadlines=[
            F24Deadline(
                due_date=d.due_date,
                fiscal_year=d.fiscal_year,
                component=TaxComponent(d.component),
                kind=TaxPaymentKind(d.kind),
                amount_due=d.amount_due,
                amount_paid=d.amount_paid,
                is_estimate=d.is_estimate,
            )
            for d in service.deadlines(ledger, year, today)
        ],
    )

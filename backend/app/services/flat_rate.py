"""
P.IVA forfettaria: the tax a flat-rate freelancer owes, how much of each
collected euro to set aside, and when the F24s fall due.

The rules, per fiscal year Y (all on a cash basis — `collected_on`):

- revenue = fee + rivalsa INPS 4% + €2 bollo charged to the client; both
  extras are revenue (the bollo since AdE risposta 428/2022);
- taxable base = revenue × profitability coefficient (78% for most
  professionals);
- INPS (gestione separata) = base × INPS rate;
- imposta sostitutiva = (base − INPS contributions *paid* in Y) × rate. The
  deduction is the law (L. 190/2014, c. 64) and is on contributions paid,
  not due — so it comes from the recorded F24s. A per-invoice estimate
  can't know it and stays gross, which errs on the safe side;
- advances for Y+1 (metodo storico) = 100% of Y's tax (none at or below
  €51.65, a single November payment below €257.52, else 40% June / 60%
  November) + 80% of Y's INPS (40% / 40%).

Two different "debts" come out of this, on purpose:

- `tax_liability`: taxes accrued on income already collected, minus every
  payment. This is what net worth subtracts. Advances paid for a year whose
  income hasn't come in yet make it negative — a credit, which is what they
  are. Counting next year's advances as debt instead would understate net
  worth by ~20% of first-year income until next year's income absorbed them.
- `cash_requirement`: everything the F24s will still ask for the income
  collected so far, next year's advances included. This is what the
  provision has to cover, and the page's gap compares against.

Everything that reads the ledger takes a `Ledger` loaded once, so the
history chart can evaluate hundreds of dates without a query per date.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date as date_
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import (
    Account,
    FlatRateProvisionSource,
    FlatRateSettings,
    FlatRateYear,
    Invoice,
    TaxPayment,
    User,
)
from app.schemas import AccountBalance, ProvisionSource, ProvisionStatus
from app.schemas import Asset as AssetSchema
from app.services import asset_prices as asset_prices_service
from app.services.asset_prices import AssetPriceUnavailable
from app.services.exchange_rates import ExchangeRateUnavailable, get_rate
from app.services.net_worth import account_balances, compute_holding_positions

CURRENCY = "EUR"
CENT = Decimal("0.01")
STAMP_DUTY_AMOUNT = Decimal("2.00")
# The bollo is due on VAT-exempt invoices above this amount.
STAMP_DUTY_THRESHOLD = Decimal("77.47")
# Above it the regime is lost from the following year (immediately above 100k).
REVENUE_LIMIT = Decimal("85000")
INPS_ADVANCE_SHARE = Decimal("0.8")
TAX_ADVANCE_MINIMUM = Decimal("51.65")
TAX_ADVANCE_SINGLE_PAYMENT_BELOW = Decimal("257.52")
TAX_FIRST_ADVANCE_SHARE = Decimal("0.4")


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _ceil_to_five_percent(value: Decimal) -> Decimal:
    return min((value * 20).to_integral_value(rounding=ROUND_CEILING) / 20, Decimal("1"))


# Imposta sostitutiva: 5% for the year the activity starts and the four
# after it, 15% from then on (L. 190/2014, c. 65).
STARTUP_TAX_RATE = Decimal("0.05")
ORDINARY_TAX_RATE = Decimal("0.15")
STARTUP_YEARS = 5


def startup_last_year(activity_start: date_ | None) -> int | None:
    return activity_start.year + STARTUP_YEARS - 1 if activity_start is not None else None


def automatic_tax_rate(year: int, activity_start: date_ | None) -> Decimal:
    """
    Without a start date there's no telling, and 15% errs on the safe side.
    The 5% has other conditions too (no similar activity in the previous
    three years, …); someone who doesn't meet them overrides the year.
    """
    last = startup_last_year(activity_start)
    if activity_start is not None and last is not None and activity_start.year <= year <= last:
        return STARTUP_TAX_RATE
    return ORDINARY_TAX_RATE


@dataclass(frozen=True)
class YearRow:
    """A year's stored parameters. A NULL tax rate means automatic."""

    profitability_coefficient: Decimal
    substitute_tax_rate: Decimal | None
    inps_rate: Decimal
    rivalsa_rate: Decimal
    provision_rate: Decimal | None = None

    @classmethod
    def from_row(cls, row: FlatRateYear) -> "YearRow":
        return cls(
            profitability_coefficient=Decimal(row.profitability_coefficient),
            substitute_tax_rate=(
                Decimal(row.substitute_tax_rate) if row.substitute_tax_rate is not None else None
            ),
            inps_rate=Decimal(row.inps_rate),
            rivalsa_rate=Decimal(row.rivalsa_rate),
            provision_rate=(
                Decimal(row.provision_rate) if row.provision_rate is not None else None
            ),
        )


@dataclass(frozen=True)
class YearParams:
    """A year's parameters with the tax rate resolved."""

    profitability_coefficient: Decimal
    substitute_tax_rate: Decimal
    inps_rate: Decimal
    rivalsa_rate: Decimal
    provision_rate: Decimal | None
    substitute_tax_rate_is_automatic: bool

    @property
    def load_rate(self) -> Decimal:
        return self.profitability_coefficient * (self.substitute_tax_rate + self.inps_rate)

    @property
    def advance_rate(self) -> Decimal:
        return self.profitability_coefficient * (
            self.substitute_tax_rate + INPS_ADVANCE_SHARE * self.inps_rate
        )


# A first year's starting point: the most common coefficient (professionals),
# gestione separata with rivalsa, and the tax rate left automatic. Every later
# year copies the one before it instead.
DEFAULT_ROW = YearRow(
    profitability_coefficient=Decimal("0.78"),
    substitute_tax_rate=None,
    inps_rate=Decimal("0.2623"),
    rivalsa_rate=Decimal("0.04"),
)


def template_row(rows: dict[int, YearRow], year: int) -> YearRow:
    """
    What a year without a row starts from: the latest year before it, else
    the earliest after it, else the defaults — minus the two per-year
    choices. The tax rate goes back to automatic (an explicit 5% copied past
    the fifth year would be wrong), the provision rate to the suggestion.
    """
    earlier = [y for y in rows if y < year]
    if earlier:
        source = rows[max(earlier)]
    elif rows:
        source = rows[min(rows)]
    else:
        source = DEFAULT_ROW
    return YearRow(
        profitability_coefficient=source.profitability_coefficient,
        substitute_tax_rate=None,
        inps_rate=source.inps_rate,
        rivalsa_rate=source.rivalsa_rate,
        provision_rate=None,
    )


# ---------------------------------------------------------------------------
# One invoice
# ---------------------------------------------------------------------------

def auto_stamp_duty(amount: Decimal, rivalsa_rate: Decimal) -> bool:
    return amount + money(amount * rivalsa_rate) > STAMP_DUTY_THRESHOLD


def rivalsa_amount(invoice: Invoice) -> Decimal:
    return money(Decimal(invoice.amount) * Decimal(invoice.rivalsa_rate))


def stamp_duty_amount(invoice: Invoice) -> Decimal:
    return STAMP_DUTY_AMOUNT if invoice.stamp_duty else Decimal("0")


def invoice_total(invoice: Invoice) -> Decimal:
    return Decimal(invoice.amount) + rivalsa_amount(invoice) + stamp_duty_amount(invoice)


def fiscal_year_of(invoice: Invoice) -> int:
    return (invoice.collected_on or invoice.issue_date).year


@dataclass(frozen=True)
class InvoiceBreakdown:
    rivalsa_amount: Decimal
    stamp_duty_amount: Decimal
    total: Decimal
    taxable_base: Decimal
    substitute_tax: Decimal
    inps: Decimal
    substitute_tax_advance: Decimal
    inps_advance: Decimal
    applied_provision_rate: Decimal
    to_provision: Decimal


def invoice_breakdown(
    invoice: Invoice, params: YearParams, year_provision_rate: Decimal
) -> InvoiceBreakdown:
    total = invoice_total(invoice)
    base = total * params.profitability_coefficient
    tax = base * params.substitute_tax_rate
    inps = base * params.inps_rate
    rate = (
        Decimal(invoice.provision_rate)
        if invoice.provision_rate is not None
        else year_provision_rate
    )
    return InvoiceBreakdown(
        rivalsa_amount=rivalsa_amount(invoice),
        stamp_duty_amount=stamp_duty_amount(invoice),
        total=total,
        taxable_base=money(base),
        substitute_tax=money(tax),
        inps=money(inps),
        substitute_tax_advance=money(tax),
        inps_advance=money(inps * INPS_ADVANCE_SHARE),
        applied_provision_rate=rate,
        to_provision=money(total * rate),
    )


# ---------------------------------------------------------------------------
# The ledger: everything a computation needs, loaded once
# ---------------------------------------------------------------------------

@dataclass
class Ledger:
    invoices: list[Invoice]  # collected ones only
    payments: list[TaxPayment]
    params: dict[int, YearRow]
    activity_start: date_ | None
    safety_margin: Decimal

    def params_for(self, year: int) -> YearParams:
        """
        The year's frozen row, its tax rate resolved. A year without a row
        (no invoice or payment ever touched it) gets what get-or-create would
        give it — see `template_row`.
        """
        row = self.params.get(year) or template_row(self.params, year)
        automatic = row.substitute_tax_rate is None
        return YearParams(
            profitability_coefficient=row.profitability_coefficient,
            substitute_tax_rate=(
                automatic_tax_rate(year, self.activity_start)
                if row.substitute_tax_rate is None
                else row.substitute_tax_rate
            ),
            inps_rate=row.inps_rate,
            rivalsa_rate=row.rivalsa_rate,
            provision_rate=row.provision_rate,
            substitute_tax_rate_is_automatic=automatic,
        )

    def collected_years(self) -> set[int]:
        return {inv.collected_on.year for inv in self.invoices if inv.collected_on}

    def is_empty(self) -> bool:
        return not self.invoices and not self.payments


@dataclass(frozen=True)
class YearFigures:
    year: int
    revenue: Decimal
    taxable_base: Decimal
    inps: Decimal
    inps_deducted: Decimal
    substitute_tax: Decimal

    @property
    def liability(self) -> Decimal:
        return self.substitute_tax + self.inps


def year_figures(ledger: Ledger, year: int, as_of: date_ | None = None) -> YearFigures:
    """Year Y's taxes on what was collected by `as_of` (default: the whole year)."""
    cutoff = as_of if as_of is not None else date_(year, 12, 31)
    revenue = sum(
        (
            invoice_total(inv)
            for inv in ledger.invoices
            if inv.collected_on is not None
            and inv.collected_on.year == year
            and inv.collected_on <= cutoff
        ),
        Decimal("0"),
    )
    params = ledger.params_for(year)
    base = revenue * params.profitability_coefficient
    inps_paid = sum(
        (
            Decimal(p.amount)
            for p in ledger.payments
            if p.component == "inps" and p.paid_on.year == year and p.paid_on <= cutoff
        ),
        Decimal("0"),
    )
    deduction = min(base, inps_paid)
    return YearFigures(
        year=year,
        revenue=money(revenue),
        taxable_base=money(base),
        inps=money(base * params.inps_rate),
        inps_deducted=money(deduction),
        substitute_tax=money((base - deduction) * params.substitute_tax_rate),
    )


@dataclass(frozen=True)
class Advances:
    tax_first: Decimal
    tax_second: Decimal
    inps_first: Decimal
    inps_second: Decimal

    @property
    def total(self) -> Decimal:
        return self.tax_first + self.tax_second + self.inps_first + self.inps_second


def advances_from(figures: YearFigures) -> Advances:
    """The advances the following year owes on `figures` (metodo storico)."""
    tax = figures.substitute_tax
    if tax <= TAX_ADVANCE_MINIMUM:
        tax_first = tax_second = Decimal("0")
    elif tax < TAX_ADVANCE_SINGLE_PAYMENT_BELOW:
        tax_first, tax_second = Decimal("0"), tax
    else:
        tax_first = money(tax * TAX_FIRST_ADVANCE_SHARE)
        tax_second = tax - tax_first
    inps_total = money(figures.inps * INPS_ADVANCE_SHARE)
    inps_first = money(inps_total / 2)
    return Advances(tax_first, tax_second, inps_first, inps_total - inps_first)


def advances_due(ledger: Ledger, year: int) -> Advances:
    return advances_from(year_figures(ledger, year - 1))


def paid(
    ledger: Ledger,
    *,
    fiscal_year: int | None = None,
    as_of: date_ | None = None,
    component: str | None = None,
    kinds: Iterable[str] | None = None,
) -> Decimal:
    kind_set = set(kinds) if kinds is not None else None
    return sum(
        (
            Decimal(p.amount)
            for p in ledger.payments
            if (fiscal_year is None or p.fiscal_year == fiscal_year)
            and (as_of is None or p.paid_on <= as_of)
            and (component is None or p.component == component)
            and (kind_set is None or p.kind in kind_set)
        ),
        Decimal("0"),
    )


def tax_liability(ledger: Ledger, as_of: date_) -> Decimal:
    """Accrued on collected income, net of every payment made by `as_of`."""
    accrued = sum(
        (
            year_figures(ledger, year, as_of).liability
            for year in ledger.collected_years()
            if year <= as_of.year
        ),
        Decimal("0"),
    )
    return accrued - paid(ledger, as_of=as_of)


def tax_cost(ledger: Ledger, date_from: date_, date_to: date_) -> Decimal:
    """
    Imposta + INPS on the invoices collected in the range — the per-invoice
    estimates the Fatture table shows, at each collection year's rates.

    What the planning engine takes off income so that "savings" means net
    profit. The per-invoice figure is the one to use here, not the year's:
    it stays gross of the INPS deduction (the safe side) and never swings
    negative in the month an F24 lowers the year's tax.
    """
    total = Decimal("0")
    for invoice in ledger.invoices:
        collected = invoice.collected_on
        if collected is None or not date_from <= collected <= date_to:
            continue
        breakdown = invoice_breakdown(invoice, ledger.params_for(collected.year), Decimal("0"))
        total += breakdown.substitute_tax + breakdown.inps
    return total


def cash_requirement(ledger: Ledger, as_of: date_) -> Decimal:
    """
    What the F24s will still ask for the income collected by `as_of`:
    closed years' balances, this year's advances (due whatever this year
    brings in) or its accrued taxes if larger, and the advances that this
    year's income already commits next year to.
    """
    current = as_of.year
    years = ledger.collected_years() | {p.fiscal_year for p in ledger.payments}
    total = Decimal("0")
    for year in years:
        if year < current:
            total += year_figures(ledger, year).liability
    current_figures = year_figures(ledger, current, as_of)
    total += max(current_figures.liability, advances_due(ledger, current).total)
    total += advances_from(current_figures).total
    # Every payment made so far covers one of the terms above (or a later
    # year's, which can only lower what's left).
    total -= paid(ledger, as_of=as_of)
    return max(total, Decimal("0"))


# ---------------------------------------------------------------------------
# Suggested provision rate
# ---------------------------------------------------------------------------

def months_active(ledger: Ledger, year: int) -> int:
    start = ledger.activity_start
    if start is None or start.year < year:
        return 12
    if start.year > year:
        return 0
    return 13 - start.month


@dataclass(frozen=True)
class RateSuggestion:
    load_rate: Decimal
    advance_rate: Decimal
    needed_rate: Decimal
    suggested_rate: Decimal


def suggest_provision_rate(ledger: Ledger, year: int) -> RateSuggestion:
    """
    Share of each euro collected in `year` the F24s will need, plus margin.

    Each euro owes its own year's taxes (load) and commits next year to
    advances on it (advance). This year's advances were already set aside
    out of last year's income, and they prepay part of this year's taxes —
    the part they cover, spread over the revenue this year is expected to
    bring (last year's, annualised on the months it was active), doesn't
    need setting aside again. Hence, with the defaults at 78% / 5% /
    26.23%: ~45% in a first year (55% with margin), ~33% the year after a
    7-month start (40%), and the plain ~24% load (30%) once steady.
    """
    params = ledger.params_for(year)
    load, advance = params.load_rate, params.advance_rate

    previous_revenue = year_figures(ledger, year - 1).revenue
    months = months_active(ledger, year - 1)
    if previous_revenue > 0 and months > 0:
        projected = previous_revenue * 12 / months
        covered = advances_due(ledger, year).total / projected
        needed = max(load, load + advance - covered)
    elif ledger.activity_start is not None and ledger.activity_start.year < year:
        # An established activity whose past isn't in the app: assume the
        # advances it pays track its income (steady state).
        needed = load
    else:
        needed = load + advance

    suggested = _ceil_to_five_percent(needed * (1 + ledger.safety_margin))
    return RateSuggestion(
        load_rate=load.quantize(Decimal("0.0001")),
        advance_rate=advance.quantize(Decimal("0.0001")),
        needed_rate=needed.quantize(Decimal("0.0001")),
        suggested_rate=suggested.quantize(Decimal("0.0001")),
    )


def effective_provision_rate(ledger: Ledger, year: int) -> Decimal:
    explicit = ledger.params_for(year).provision_rate
    if explicit is not None:
        return explicit
    return suggest_provision_rate(ledger, year).suggested_rate


# ---------------------------------------------------------------------------
# F24 deadlines
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Deadline:
    due_date: date_
    fiscal_year: int
    component: str
    kind: str
    amount_due: Decimal
    amount_paid: Decimal
    is_estimate: bool


def deadlines(ledger: Ledger, year: int, as_of: date_) -> list[Deadline]:
    """
    The F24s falling due in `year` and the next one: 30 June (balance of
    the year before + first advance), 30 November (second advance). Based
    on a year still in progress, they're estimates on what's collected so
    far.
    """
    result: list[Deadline] = []
    for due_year in (year, year + 1):
        basis = due_year - 1
        closed = as_of > date_(basis, 12, 31)
        figures = year_figures(ledger, basis, None if closed else as_of)
        advances = advances_from(figures)
        advance_kinds = ("first_advance", "second_advance")
        balance_tax = max(
            figures.substitute_tax
            - paid(ledger, fiscal_year=basis, component="substitute_tax", kinds=advance_kinds),
            Decimal("0"),
        )
        balance_inps = max(
            figures.inps
            - paid(ledger, fiscal_year=basis, component="inps", kinds=advance_kinds),
            Decimal("0"),
        )
        june, november = date_(due_year, 6, 30), date_(due_year, 11, 30)
        rows = [
            (june, basis, "substitute_tax", "balance", balance_tax),
            (june, basis, "inps", "balance", balance_inps),
            (june, due_year, "substitute_tax", "first_advance", advances.tax_first),
            (june, due_year, "inps", "first_advance", advances.inps_first),
            (november, due_year, "substitute_tax", "second_advance", advances.tax_second),
            (november, due_year, "inps", "second_advance", advances.inps_second),
        ]
        for due_date, fiscal_year, component, kind, amount_due in rows:
            amount_paid = paid(
                ledger, fiscal_year=fiscal_year, component=component, kinds=(kind,)
            )
            if amount_due == 0 and amount_paid == 0:
                continue
            result.append(
                Deadline(
                    due_date=due_date,
                    fiscal_year=fiscal_year,
                    component=component,
                    kind=kind,
                    amount_due=amount_due,
                    amount_paid=amount_paid,
                    is_estimate=not closed,
                )
            )
    return result


# ---------------------------------------------------------------------------
# Database access
# ---------------------------------------------------------------------------

def get_or_create_settings(db: Session, user: User) -> FlatRateSettings:
    existing = db.query(FlatRateSettings).filter(FlatRateSettings.user_id == user.id).first()
    if existing is not None:
        return existing
    db.execute(
        pg_insert(FlatRateSettings)
        .values(user_id=user.id)
        .on_conflict_do_nothing(index_elements=["user_id"])
    )
    db.flush()
    return db.query(FlatRateSettings).filter(FlatRateSettings.user_id == user.id).one()


def get_or_create_year(db: Session, user: User, year: int) -> FlatRateYear:
    """
    The year's parameters, created on first use from `template_row` and
    never recomputed afterwards — except an automatic tax rate, which is
    derived from the activity's start date on every read. Flushes; the
    caller commits.
    """
    rows = db.query(FlatRateYear).filter(FlatRateYear.user_id == user.id).all()
    by_year = {row.year: row for row in rows}
    if year in by_year:
        return by_year[year]

    template = template_row({y: YearRow.from_row(r) for y, r in by_year.items()}, year)
    db.execute(
        pg_insert(FlatRateYear)
        .values(
            user_id=user.id,
            year=year,
            profitability_coefficient=template.profitability_coefficient,
            substitute_tax_rate=template.substitute_tax_rate,
            inps_rate=template.inps_rate,
            rivalsa_rate=template.rivalsa_rate,
            provision_rate=template.provision_rate,
        )
        .on_conflict_do_nothing(index_elements=["user_id", "year"])
    )
    db.flush()
    return (
        db.query(FlatRateYear)
        .filter(FlatRateYear.user_id == user.id, FlatRateYear.year == year)
        .one()
    )


def load_ledger(db: Session, user: User) -> Ledger:
    invoices = (
        db.query(Invoice)
        .filter(
            Invoice.user_id == user.id,
            Invoice.deleted_at.is_(None),
            Invoice.collected_on.isnot(None),
        )
        .all()
    )
    payments = (
        db.query(TaxPayment)
        .filter(TaxPayment.user_id == user.id, TaxPayment.deleted_at.is_(None))
        .all()
    )
    years = db.query(FlatRateYear).filter(FlatRateYear.user_id == user.id).all()
    settings = db.query(FlatRateSettings).filter(FlatRateSettings.user_id == user.id).first()
    return Ledger(
        invoices=invoices,
        payments=payments,
        params={row.year: YearRow.from_row(row) for row in years},
        activity_start=settings.activity_start_date if settings else None,
        safety_margin=(
            Decimal(settings.safety_margin) if settings else Decimal("0.15")
        ),
    )


def active_sources(db: Session, user: User) -> list[FlatRateProvisionSource]:
    return (
        db.query(FlatRateProvisionSource)
        .join(Account, Account.id == FlatRateProvisionSource.account_id)
        .filter(
            FlatRateProvisionSource.user_id == user.id,
            FlatRateProvisionSource.deleted_at.is_(None),
            Account.deleted_at.is_(None),
        )
        .order_by(FlatRateProvisionSource.created_at)
        .all()
    )


def earmarked_cash(
    db: Session, user: User, balances: list[AccountBalance] | None = None
) -> Decimal:
    """Cash sitting in provision accounts, in base currency — already the State's."""
    account_ids = {s.account_id for s in active_sources(db, user) if s.asset_id is None}
    if not account_ids:
        return Decimal("0")
    if balances is None:
        balances = account_balances(db, user)
    return sum(
        (b.balance_base_currency for b in balances if b.account_id in account_ids),
        Decimal("0"),
    )


def provision_status(db: Session, user: User) -> ProvisionStatus:
    """
    What's set aside right now, valued live. Prices and rates are fetched
    per held product, so like `holdings_with_value` this flushes cache rows
    the caller must commit.
    """
    today = date_.today()
    sources = active_sources(db, user)
    balances = {b.account_id: b for b in account_balances(db, user)}
    positions = (
        compute_holding_positions(db, user) if any(s.asset_id for s in sources) else {}
    )
    cash_accounts = {s.account_id for s in sources if s.asset_id is None}

    def to_base(amount: Decimal, currency: str) -> Decimal | None:
        if currency == user.base_currency:
            return amount
        try:
            return amount * get_rate(db, currency, user.base_currency, today)
        except ExchangeRateUnavailable:
            return None

    rows: list[ProvisionSource] = []
    for source in sources:
        account = source.account
        balance = balances.get(account.id)
        if source.asset_id is None:
            rows.append(
                ProvisionSource(
                    id=source.id,
                    account_id=account.id,
                    account_name=account.name,
                    account_currency=account.currency,
                    asset=None,
                    quantity=None,
                    price=None,
                    value_base_currency=(
                        balance.balance_base_currency if balance else Decimal("0")
                    ),
                    buyable_units=None,
                )
            )
            continue

        asset = source.asset
        assert asset is not None
        position = positions.get((account.id, asset.id))
        quantity = position["quantity"] if position else Decimal("0")
        quantity = max(quantity, Decimal("0"))
        try:
            price: Decimal | None = asset_prices_service.get_price(db, asset, today)
        except AssetPriceUnavailable:
            price = None
        value = to_base(quantity * price, asset.currency) if price is not None else None

        buyable = None
        if (
            price is not None
            and price > 0
            and account.id in cash_accounts
            and balance is not None
            and account.currency == asset.currency
        ):
            buyable = max(
                int((Decimal(balance.balance) / price).to_integral_value(rounding=ROUND_FLOOR)),
                0,
            )
        rows.append(
            ProvisionSource(
                id=source.id,
                account_id=account.id,
                account_name=account.name,
                account_currency=account.currency,
                asset=AssetSchema.model_validate(asset),
                quantity=quantity,
                price=price,
                value_base_currency=value,
                buyable_units=buyable,
            )
        )

    total = sum(
        (r.value_base_currency for r in rows if r.value_base_currency is not None),
        Decimal("0"),
    )
    return ProvisionStatus(total_base_currency=total, sources=rows)


def liability_in_base_currency(
    db: Session, user: User, amount: Decimal, on_date: date_
) -> Decimal:
    """
    Liabilities are EUR; a non-EUR base currency converts them. A rate that
    can't be fetched leaves the liability out rather than 500ing net worth,
    as an unpriced asset is left out.
    """
    if amount == 0 or user.base_currency == CURRENCY:
        return amount
    try:
        return amount * get_rate(db, CURRENCY, user.base_currency, on_date)
    except ExchangeRateUnavailable:
        return Decimal("0")


def tax_cost_in_base_currency(
    db: Session, user: User, *, date_from: date_, date_to: date_
) -> Decimal:
    """`tax_cost` for a user, converted like the liability (at today's rate at most)."""
    ledger = load_ledger(db, user)
    if not ledger.invoices:
        return Decimal("0")
    cost = tax_cost(ledger, date_from, date_to)
    return liability_in_base_currency(db, user, cost, min(date_to, date_.today()))


def source_account_ids(db: Session, user: User, *, cash_only: bool = False) -> set[UUID]:
    return {
        s.account_id
        for s in active_sources(db, user)
        if not cash_only or s.asset_id is None
    }

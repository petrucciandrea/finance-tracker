"""
Create a demo user with six months of history: `python -m app.seed_demo [--reset]`.

For local use only (it refuses to run when ENVIRONMENT=production). Everything is
written straight through the ORM and the same service helpers the routers use, so
the data obeys the app's own rules: frozen exchange rates, transfers paired with
their counterpart, buys/sells with their cash leg, "Varie" never needed.

Prices and rates are the *real* historical ones, fetched through the normal cache
services. Inventing them would poison the shared `asset_prices` / `exchange_rates`
tables, which every user (the owner's real account included) reads from. So this
needs network access, and a failed fetch aborts the whole run before anything is
committed.

The demo user is a freelance designer on a P.IVA forfettaria opened in June 2025: no
salary, the income is invoices, a share of each goes to a tax account, and the F24s
already due are paid from it (see `Seeder.flat_rate`).

The random generator is seeded: the same day gives the same spending, which makes the
demo reproducible. `--reset` erases the demo user first (same erasure as GDPR art. 17).
"""

import argparse
import calendar
import os
import random
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from datetime import date as date_
from decimal import ROUND_DOWN, Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import (
    Account,
    Asset,
    AssetTransaction,
    Category,
    FlatRateProvisionSource,
    FlatRateYear,
    Invoice,
    PhysicalAsset,
    PhysicalAssetMovement,
    PhysicalAssetValuation,
    SavingsGoal,
    SavingsGoalSource,
    TaxPayment,
    Transaction,
    User,
)
from app.services import asset_prices
from app.services import flat_rate as flat_rate_service
from app.services.exchange_rates import get_rate, get_rate_history
from app.services.physical_assets import METAL_SYMBOLS, TROY_OUNCE_GRAMS, metal_asset
from app.services.transfers import create_cash_leg, create_linked_transfer
from app.services.user_data import erase_user

DEMO_EMAIL = "demo@example.com"
# Known on purpose: this account only ever exists in a local database.
DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD", "DemoPass2026!")
BASE_CURRENCY = "EUR"
MONTHS = 6

CENT = Decimal("0.01")


def money(value: float | str | Decimal) -> Decimal:
    return Decimal(str(value)).quantize(CENT)


# ---------------------------------------------------------------------------
# Categories: (parent, necessity level, [(child, level overriding the parent's)])
# ---------------------------------------------------------------------------

EXPENSE_TREE: list[tuple[str, str, list[tuple[str, str | None]]]] = [
    (
        "Casa",
        "primary",
        [
            ("Affitto", None),
            ("Luce e gas", None),
            ("Internet e telefono", None),
            ("Spese condominiali", None),
        ],
    ),
    (
        "Alimentari",
        "primary",
        [("Spesa", None), ("Ristoranti e bar", "discretionary"), ("Delivery", "discretionary")],
    ),
    (
        "Trasporti",
        "primary",
        [("Carburante", None), ("Assicurazione auto", None), ("Treni e mezzi", "useful")],
    ),
    ("Salute", "primary", [("Farmacia", None), ("Visite mediche", None)]),
    (
        "Svago",
        "discretionary",
        [("Streaming e abbonamenti", None), ("Cinema e eventi", None), ("Libri e hobby", None)],
    ),
    (
        "Shopping",
        "discretionary",
        [("Abbigliamento", "useful"), ("Elettronica", None), ("Regali", None)],
    ),
    ("Benessere", "useful", [("Palestra", None), ("Cura della persona", None)]),
    ("Viaggi", "discretionary", [("Voli", None), ("Alloggi", None)]),
]
INCOME_CATEGORIES = ["Fatture", "Interessi", "Dividendi", "Rimborsi"]
TRANSFER_CATEGORIES = [
    "Risparmio",
    "Investimenti",
    "Prelievo contanti",
    "Ricarica conti",
    "Accantonamento tasse",
    "F24",
]

# ---------------------------------------------------------------------------
# P.IVA forfettaria: a graphic designer who quit their job and opened it here
# ---------------------------------------------------------------------------

ACTIVITY_START = date_(2025, 6, 3)
# Small local clients at first, then a monthly retainer and bigger projects.
FIRST_CLIENTS = ["Panificio Rinaldi", "B&B Le Rondini", "Studio Dentistico Galli"]
RETAINER_CLIENT = "Rossi Digital Srl"
PROJECT_CLIENTS = ["Studio Bianchi Architetti", "Ferretti Comunicazione", "Agenzia Lumen"]
# Monthly fees grow by this much from the first month: ~600 € in June 2025, ~5,000 € by
# late 2026. That growth is the point: the 2026 advances, computed on a small 2025, cover
# a fraction of 2026's taxes, and the June 2027 balance shows what is left.
FIRST_MONTH_FEES = 600
MONTHLY_GROWTH = 280
# Above this a month's work is split between the retainer and a project.
SPLIT_ABOVE = 2000
F24_KIND_LABELS = {
    "balance": "saldo",
    "first_advance": "1° acconto",
    "second_advance": "2° acconto",
}
F24_TAX_LABELS = {"substitute_tax": "imposta sostitutiva", "inps": "INPS"}


def create_categories(db: Session, user: User) -> dict[str, Category]:
    by_name: dict[str, Category] = {}

    def add(name: str, type_: str, parent: Category | None = None, **extra: object) -> None:
        category = Category(
            user_id=user.id,
            name=name,
            type=type_,
            parent_id=parent.id if parent else None,
            **extra,
        )
        db.add(category)
        db.flush()
        by_name[name] = category

    for parent_name, level, children in EXPENSE_TREE:
        add(parent_name, "expense", necessity_level=level)
        for child_name, child_level in children:
            # Left NULL when it matches the parent: that is what exercises inheritance.
            add(child_name, "expense", by_name[parent_name], necessity_level=child_level)
    for name in INCOME_CATEGORIES:
        add(name, "income", excluded_from_income_base=(name == "Rimborsi"))
    for name in TRANSFER_CATEGORIES:
        add(name, "transfer")
    return by_name


# ---------------------------------------------------------------------------
# The generator
# ---------------------------------------------------------------------------


class Seeder:
    def __init__(self, db: Session, user: User, today: date_) -> None:
        self.db = db
        self.user = user
        self.today = today
        self.rng = random.Random(2026)
        first_of_month = today.replace(day=1)
        month_index = first_of_month.year * 12 + first_of_month.month - 1 - MONTHS
        self.start = date_(month_index // 12, month_index % 12 + 1, 1)
        self.cat: dict[str, Category] = {}
        self.acc: dict[str, Account] = {}
        self.assets: dict[str, Asset] = {}
        self.price_history: dict[str, dict[date_, Decimal]] = {}
        self.held: dict[str, Decimal] = defaultdict(Decimal)

    # -- small helpers ------------------------------------------------------

    def months(self) -> list[tuple[int, int]]:
        out = []
        year, month = self.start.year, self.start.month
        while date_(year, month, 1) <= self.today:
            out.append((year, month))
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        return out

    def business_day(self, day: date_) -> date_:
        """A bank moves money on working days: weekends slide back to Friday."""
        while day.weekday() >= 5:
            day -= timedelta(days=1)
        return day

    def on(self, year: int, month: int, day: int) -> date_ | None:
        """That day of the month, clamped to the month, or None if it is still ahead."""
        day = min(day, calendar.monthrange(year, month)[1])
        result = self.business_day(date_(year, month, day))
        return result if self.start <= result <= self.today else None

    def random_day(self, year: int, month: int) -> date_ | None:
        last = calendar.monthrange(year, month)[1]
        result = date_(year, month, self.rng.randint(1, last))
        return result if self.start <= result <= self.today else None

    def amount(self, low: float, high: float) -> Decimal:
        return money(self.rng.uniform(low, high))

    # -- writers ------------------------------------------------------------

    def spend(self, account: str, day: date_ | None, value: Decimal, category: str, desc: str):
        if day is None:
            return
        self._tx(account, day, -value, category, desc, "expense")

    def earn(self, account: str, day: date_ | None, value: Decimal, category: str, desc: str):
        if day is None:
            return
        self._tx(account, day, value, category, desc, "income")

    def _tx(self, account: str, day: date_, signed: Decimal, category: str, desc: str, type_: str):
        acct = self.acc[account]
        rate = get_rate(self.db, acct.currency, BASE_CURRENCY, day)
        self.db.add(
            Transaction(
                account_id=acct.id,
                category_id=self.cat[category].id,
                amount=signed,
                currency=acct.currency,
                amount_base_currency=signed * rate,
                exchange_rate=rate,
                date=day,
                description=desc,
                type=type_,
                source="manual",
            )
        )

    def transfer(self, src: str, dst: str, day: date_ | None, value: Decimal, desc: str, cat: str):
        if day is None:
            return
        create_linked_transfer(
            self.db,
            self.user,
            from_account=self.acc[src],
            to_account=self.acc[dst],
            amount=value,
            on_date=day,
            description=desc,
            category_id=self.cat[cat].id,
        )

    def open_account(
        self, key: str, name: str, type_: str, currency: str, opening: Decimal
    ) -> None:
        account = Account(user_id=self.user.id, name=name, type=type_, currency=currency)
        self.db.add(account)
        self.db.flush()
        self.acc[key] = account
        if opening:
            # Same shape as POST /accounts: an opening balance is a `transfer` with no category.
            rate = get_rate(self.db, currency, BASE_CURRENCY, self.start)
            self.db.add(
                Transaction(
                    account_id=account.id,
                    category_id=None,
                    amount=opening,
                    currency=currency,
                    amount_base_currency=opening * rate,
                    exchange_rate=rate,
                    date=self.start,
                    description="Saldo iniziale",
                    type="transfer",
                    source="manual",
                )
            )

    # -- investments --------------------------------------------------------

    def load_market_data(self, symbols: dict[str, str]) -> None:
        """Pull real price history for every symbol, plus USD/EUR, into the shared caches."""
        window_start = self.start - timedelta(days=10)
        get_rate_history(self.db, "USD", BASE_CURRENCY, window_start, self.today)
        for symbol, asset_type in symbols.items():
            asset = asset_prices.find_or_create_asset(self.db, symbol, asset_type)
            self.assets[symbol] = asset
            history = asset_prices.get_price_history(self.db, asset, window_start, self.today)
            if not history:
                sys.exit(f"No price history available for {symbol}.")
            self.price_history[symbol] = history
            # Today's quote is what holdings are valued at.
            asset_prices.get_price(self.db, asset, self.today)

    def price_on(self, symbol: str, day: date_) -> Decimal:
        history = self.price_history[symbol]
        for back in range(8):  # weekends and holidays have no close: take the last one
            found = history.get(day - timedelta(days=back))
            if found is not None:
                return found
        sys.exit(f"No price for {symbol} around {day}.")

    def trade(
        self,
        account: str,
        symbol: str,
        day: date_ | None,
        kind: str,
        *,
        budget: Decimal | None = None,
        quantity: Decimal | None = None,
        fee: Decimal = Decimal("0"),
        fee_pct: Decimal | None = None,
        decimals: int = 0,
    ) -> None:
        """Buy for roughly `budget` (whole units unless `decimals`) or move `quantity`."""
        if day is None:
            return
        acct = self.acc[account]
        asset = self.assets[symbol]
        price = self.price_on(symbol, day)
        if quantity is None:
            assert budget is not None
            step = Decimal(1).scaleb(-decimals)
            quantity = (budget / price).quantize(step, rounding=ROUND_DOWN)
        if quantity <= 0:
            sys.exit(f"Budget too small to buy any {symbol} on {day}.")
        gross = quantity * price
        if fee_pct is not None:
            fee = (gross * fee_pct).quantize(CENT)
        total = gross + fee if kind == "buy" else gross - fee

        rate = get_rate(self.db, asset.currency, BASE_CURRENCY, day)
        cash = create_cash_leg(
            self.db,
            account=acct,
            amount=-total if kind == "buy" else total,
            currency=asset.currency,
            rate=rate,
            on_date=day,
            description=f"{'Acquisto' if kind == 'buy' else 'Vendita'} {symbol}",
            category_id=self.cat["Investimenti"].id,
        )
        self.held[symbol] += quantity if kind == "buy" else -quantity
        self.db.add(
            AssetTransaction(
                account_id=acct.id,
                asset_id=asset.id,
                transaction_id=cash.id,
                type=kind,
                quantity=quantity,
                price=price,
                fee=fee,
                amount_base_currency=total * rate,
                exchange_rate=rate,
                date=day,
            )
        )

    # -- the story ----------------------------------------------------------

    def build(self) -> None:
        self.cat = create_categories(self.db, self.user)

        # Several current accounts on purpose: the bank where the salary lands, a card
        # for daily spending, and one for the fixed costs of the house.
        self.open_account("intesa", "Intesa Sanpaolo", "checking", "EUR", money(3500))
        self.open_account("revolut", "Revolut", "checking", "EUR", money(500))
        self.open_account("n26", "N26 Casa", "checking", "EUR", money(400))
        self.open_account("deposito", "Conto Deposito", "savings", "EUR", money(6000))
        self.open_account("contanti", "Contanti", "cash", "EUR", money(120))
        self.open_account("directa", "Directa", "investment", "EUR", money(5000))
        self.open_account("ibkr", "Interactive Brokers", "investment", "USD", money(10500))
        self.open_account("binance", "Binance", "crypto_wallet", "USD", money(3500))
        self.db.flush()

        self.load_market_data(
            {
                "VWCE.DE": "etf",
                "EUNL.DE": "etf",
                "ENI.MI": "stock",
                "AAPL": "stock",
                "MSFT": "stock",
                "KO": "stock",
                "NVDA": "stock",
                "BTC": "crypto",
                "ETH": "crypto",
                "SOL": "crypto",
            }
        )

        for year, month in self.months():
            self.month_of_current_accounts(year, month)
        self.one_offs()
        self.investments()
        self.physical_assets()
        self.goals()
        # Last: it draws from the same random generator, and going after everything else
        # leaves the spending above identical to what it was before the P.IVA existed.
        self.flat_rate()

    def month_of_current_accounts(self, year: int, month: int) -> None:
        on, rng = self.on, self.rng

        # Income comes from the invoices (see `flat_rate`), not from a salary.

        # Moving money between own accounts
        self.transfer(
            "intesa", "n26", on(year, month, 1), money(1000), "Ricarica N26", "Ricarica conti"
        )
        self.transfer(
            "intesa",
            "revolut",
            on(year, month, 2),
            money(500),
            "Ricarica Revolut",
            "Ricarica conti",
        )
        self.transfer(
            "intesa",
            "revolut",
            on(year, month, 16),
            money(300),
            "Ricarica Revolut",
            "Ricarica conti",
        )
        self.transfer(
            "intesa",
            "deposito",
            on(year, month, 28),
            money(250),
            "Accantonamento mensile",
            "Risparmio",
        )
        self.transfer(
            "intesa", "directa", on(year, month, 4), money(300), "PAC mensile", "Investimenti"
        )
        self.transfer(
            "revolut",
            "contanti",
            on(year, month, 12),
            money(60),
            "Prelievo bancomat",
            "Prelievo contanti",
        )

        # Fixed costs from the house account
        self.spend("n26", on(year, month, 3), money(780), "Affitto", "Affitto")
        self.spend("n26", on(year, month, 10), money("27.90"), "Internet e telefono", "Fibra casa")
        self.spend(
            "n26", on(year, month, 20), money("9.99"), "Internet e telefono", "Ricarica mobile"
        )
        gas = {
            4: 55,
            5: 38,
            6: 22,
            7: 18,
            8: 17,
            9: 24,
            10: 40,
            11: 62,
            12: 85,
            1: 90,
            2: 75,
            3: 60,
        }
        self.spend(
            "n26", on(year, month, 21), money(gas[month] + rng.uniform(-3, 3)), "Luce e gas", "Gas"
        )
        if month % 2 == 0:
            self.spend(
                "n26", on(year, month, 18), self.amount(68, 96), "Luce e gas", "Energia elettrica"
            )
        if month % 3 == 1:
            self.spend(
                "n26", on(year, month, 8), money(60), "Spese condominiali", "Quota condominio"
            )

        # Subscriptions and habits
        self.spend(
            "revolut", on(year, month, 8), money("13.99"), "Streaming e abbonamenti", "Netflix"
        )
        self.spend(
            "revolut", on(year, month, 12), money("10.99"), "Streaming e abbonamenti", "Spotify"
        )
        self.spend(
            "revolut", on(year, month, 15), money("2.99"), "Streaming e abbonamenti", "iCloud"
        )
        self.spend("intesa", on(year, month, 5), money(39), "Palestra", "Abbonamento palestra")

        # Daily life: random days, random places, amounts in a plausible range
        shops = ["Esselunga", "Coop", "Conad", "Lidl", "Carrefour Express"]
        for _ in range(rng.randint(8, 10)):
            self.spend(
                "revolut",
                self.random_day(year, month),
                self.amount(14, 58),
                "Spesa",
                rng.choice(shops),
            )
        places = [
            "Pizzeria Da Mario",
            "Trattoria del Borgo",
            "Aperitivo",
            "Sushi",
            "Osteria",
            "Bar Centrale",
        ]
        for _ in range(rng.randint(3, 5)):
            self.spend(
                "revolut",
                self.random_day(year, month),
                self.amount(18, 62),
                "Ristoranti e bar",
                rng.choice(places),
            )
        for _ in range(rng.randint(1, 3)):
            self.spend(
                "revolut",
                self.random_day(year, month),
                self.amount(15, 28),
                "Delivery",
                rng.choice(["Glovo", "Deliveroo"]),
            )
        for _ in range(rng.randint(2, 3)):
            self.spend(
                "intesa",
                self.random_day(year, month),
                self.amount(42, 66),
                "Carburante",
                "Eni Station",
            )
        for _ in range(2):
            self.spend(
                "revolut",
                self.random_day(year, month),
                self.amount(8, 36),
                "Treni e mezzi",
                rng.choice(["Trenitalia", "Italo", "ATM Milano"]),
            )
        self.spend(
            "revolut", self.random_day(year, month), self.amount(8, 30), "Farmacia", "Farmacia"
        )
        self.spend(
            "revolut",
            self.random_day(year, month),
            self.amount(30, 110),
            "Abbigliamento",
            rng.choice(["Zara", "H&M", "Decathlon", "Uniqlo"]),
        )
        for _ in range(rng.randint(1, 2)):
            self.spend(
                "revolut",
                self.random_day(year, month),
                self.amount(10, 30),
                "Cinema e eventi",
                rng.choice(["Cinema", "Concerto", "Teatro"]),
            )
        self.spend(
            "revolut",
            self.random_day(year, month),
            self.amount(15, 35),
            "Libri e hobby",
            rng.choice(["Libreria", "Amazon Libri", "Mondadori"]),
        )
        self.spend(
            "intesa",
            self.random_day(year, month),
            self.amount(20, 40),
            "Cura della persona",
            "Parrucchiere",
        )
        for _ in range(3):
            self.spend(
                "contanti",
                self.random_day(year, month),
                self.amount(2, 16),
                "Ristoranti e bar",
                rng.choice(["Caffè", "Panino", "Gelato"]),
            )

    def one_offs(self) -> None:
        """Things that don't happen every month, pinned to the months they make sense in."""
        # Anchored to the seeded window rather than hard-coded months, so the story
        # still has a bonus, a holiday and so on whenever the command is run.
        months = self.months()

        def in_window(offset: int, day: int) -> date_ | None:
            if offset >= len(months):
                return None
            year, month = months[offset]
            return self.on(year, month, day)

        self.earn("revolut", in_window(2, 3), money(64), "Rimborsi", "Rimborso reso Zalando")
        self.spend(
            "intesa", in_window(1, 12), money(480), "Assicurazione auto", "Polizza RCA annuale"
        )
        self.spend("intesa", in_window(1, 20), money(90), "Visite mediche", "Visita dermatologica")
        self.spend("intesa", in_window(4, 9), money(120), "Visite mediche", "Visita oculistica")
        self.spend("revolut", in_window(2, 21), money(229), "Elettronica", "Cuffie wireless")
        self.spend("revolut", in_window(2, 30), money(60), "Regali", "Regalo compleanno")
        # The summer holiday, paid for out of the savings account.
        self.transfer(
            "deposito", "revolut", in_window(3, 14), money(800), "Risparmi per vacanza", "Risparmio"
        )
        self.spend("revolut", in_window(3, 15), money(340), "Voli", "Volo Ryanair")
        self.spend("revolut", in_window(4, 6), money(520), "Alloggi", "Booking.com")
        # Interest on the savings account, credited at month end.
        for year, month in months:
            last = date_(year, month, calendar.monthrange(year, month)[1])
            if last <= self.today:
                self.earn("deposito", last, self.amount(9.5, 12.5), "Interessi", "Interessi netti")

    def investments(self) -> None:
        months = self.months()
        s = self.start
        first_trading = self.business_day(s + timedelta(days=1))

        # Directa: a lump sum already invested at the start, then a monthly plan.
        self.trade(
            "directa", "VWCE.DE", first_trading, "buy", budget=money(2000), fee=money("2.95")
        )
        self.trade(
            "directa", "EUNL.DE", first_trading, "buy", budget=money(1300), fee=money("2.95")
        )
        for year, month in months:
            self.trade(
                "directa",
                "EUNL.DE",
                self.on(year, month, 5),
                "buy",
                budget=money(285),
                fee=money("2.95"),
            )
        if len(months) > 1:
            self.trade(
                "directa",
                "ENI.MI",
                self.on(*months[1], 6),
                "buy",
                budget=money(1100),
                fee=money("2.95"),
            )
        if len(months) > 5:
            # Partial sale: gives the portfolio a realised result.
            self.trade(
                "directa",
                "ENI.MI",
                self.on(*months[5], 15),
                "sell",
                quantity=Decimal(30),
                fee=money("2.95"),
            )

        # Interactive Brokers: US stocks in dollars.
        usd_day = self.business_day(s + timedelta(days=2))
        self.trade("ibkr", "AAPL", usd_day, "buy", budget=money(3000), fee=money(1))
        self.trade("ibkr", "MSFT", usd_day, "buy", budget=money(3000), fee=money(1))
        self.trade("ibkr", "KO", usd_day, "buy", budget=money(1500), fee=money(1))
        if len(months) > 2:
            self.trade(
                "ibkr", "NVDA", self.on(*months[2], 16), "buy", budget=money(1000), fee=money(1)
            )
        if len(months) > 5:
            self.trade(
                "ibkr", "AAPL", self.on(*months[5], 3), "buy", budget=money(800), fee=money(1)
            )
            self.trade(
                "ibkr", "KO", self.on(*months[5], 22), "sell", quantity=Decimal(10), fee=money(1)
            )
        # Quarterly dividend on Coca-Cola, after the first lot is held.
        ko_held = self.held["KO"]
        for offset in (3, 6):
            if offset < len(months):
                year, month = months[offset]
                dividend = (ko_held * Decimal("0.51") * Decimal("0.85")).quantize(CENT)
                self.earn(
                    "ibkr", self.on(year, month, 1), dividend, "Dividendi", "Dividendo KO (netto)"
                )

        # Binance: crypto, in dollars.
        crypto_day = s + timedelta(days=5)
        self.trade(
            "binance",
            "BTC",
            crypto_day,
            "buy",
            budget=money(1500),
            fee_pct=Decimal("0.001"),
            decimals=6,
        )
        self.trade(
            "binance",
            "ETH",
            crypto_day,
            "buy",
            budget=money(800),
            fee_pct=Decimal("0.001"),
            decimals=6,
        )
        if len(months) > 2:
            self.trade(
                "binance",
                "SOL",
                self.on(*months[2], 9),
                "buy",
                budget=money(400),
                fee_pct=Decimal("0.001"),
                decimals=4,
            )
        if len(months) > 4:
            self.trade(
                "binance",
                "BTC",
                self.on(*months[4], 11),
                "buy",
                budget=money(300),
                fee_pct=Decimal("0.001"),
                decimals=6,
            )
        if len(months) > 5:
            self.trade(
                "binance",
                "ETH",
                self.on(*months[5], 29),
                "sell",
                quantity=Decimal("0.05"),
                fee_pct=Decimal("0.001"),
            )

    # -- physical assets ----------------------------------------------------

    def load_metal_spots(self, first_day: date_) -> None:
        """Real COMEX spot history (USD/oz) for the metals, from before the oldest purchase."""
        get_rate_history(self.db, "USD", BASE_CURRENCY, first_day, self.today)
        for metal, symbol in METAL_SYMBOLS.items():
            if metal == "platinum":
                continue
            asset = metal_asset(self.db, metal)
            if asset is None:
                sys.exit(f"The {metal} spot asset is missing: is the database migrated?")
            history = asset_prices.get_price_history(self.db, asset, first_day, self.today)
            if not history:
                sys.exit(f"No spot history available for {metal}.")
            self.price_history[symbol] = history
            asset_prices.get_price(self.db, asset, self.today)

    def metal_price(
        self, metal: str, grams: Decimal, purity: Decimal, day: date_, factor: Decimal
    ) -> Decimal:
        """What `grams` of the alloy cost in EUR: fine content at spot times a dealer factor."""
        spot_usd_per_oz = self.price_on(METAL_SYMBOLS[metal], day)
        usd_to_base = get_rate(self.db, "USD", BASE_CURRENCY, day)
        return money(grams * purity * spot_usd_per_oz / TROY_OUNCE_GRAMS * usd_to_base * factor)

    def add_vehicle(
        self,
        name: str,
        vehicle_type: str,
        bought: date_,
        price: Decimal,
        depreciation: str,
        valuations: list[tuple[date_, Decimal, str]] | None = None,
    ) -> None:
        # Bought before the history starts, so no cash leg: nothing to pay it from.
        asset = PhysicalAsset(
            user_id=self.user.id,
            kind="vehicle",
            name=name,
            currency=BASE_CURRENCY,
            vehicle_type=vehicle_type,
            depreciation_rate=Decimal(depreciation),
            purchase_date=bought,
            purchase_price=price,
            purchase_price_base_currency=price,
        )
        self.db.add(asset)
        self.db.flush()
        for day, value, notes in valuations or []:
            self.db.add(
                PhysicalAssetValuation(
                    physical_asset_id=asset.id, date=day, value=value, notes=notes
                )
            )

    def add_metal(
        self,
        name: str,
        metal: str,
        form: str,
        purity: str,
        movements: list[tuple[str, date_ | None, str, Decimal | None, str | None]],
    ) -> None:
        """
        A position built from (type, day, grams, dealer factor, paid from / collected into).
        A factor of None is a gift: no price, so the cost stays unknown. A day in the future
        (the history is shorter than the story) skips the movement.
        """
        fine = Decimal(purity)
        asset = PhysicalAsset(
            user_id=self.user.id,
            kind="metal",
            name=name,
            currency=BASE_CURRENCY,
            metal=metal,
            metal_form=form,
            purity=fine,
        )
        self.db.add(asset)
        self.db.flush()
        for kind, day, grams_text, factor, account in movements:
            if day is None:
                continue
            grams = Decimal(grams_text)
            price = (
                self.metal_price(metal, grams, fine, day, factor) if factor is not None else None
            )
            leg = None
            if account is not None and price is not None:
                verb = "Acquisto" if kind == "buy" else "Vendita"
                leg = create_cash_leg(
                    self.db,
                    account=self.acc[account],
                    amount=-price if kind == "buy" else price,
                    currency=BASE_CURRENCY,
                    rate=Decimal(1),
                    on_date=day,
                    description=f"{verb} {grams_text.replace('.', ',')} g {name}",
                    category_id=self.cat["Investimenti"].id,
                )
            self.db.add(
                PhysicalAssetMovement(
                    physical_asset_id=asset.id,
                    type=kind,
                    date=day,
                    weight_grams=grams,
                    price=price,
                    price_base_currency=price,
                    transaction_id=leg.id if leg else None,
                )
            )

    def physical_assets(self) -> None:
        months = self.months()

        def ago(days: int) -> date_:
            return self.business_day(self.start - timedelta(days=days))

        def month_day(index: int, day: int) -> date_ | None:
            return self.on(*months[index], day) if index < len(months) else None

        self.load_metal_spots(ago(160))

        # Vehicles bought years ago; the car has had a dealer appraisal since.
        self.add_vehicle(
            "Volkswagen Golf 1.6 TDI",
            "car",
            date_(2021, 9, 18),
            money(16800),
            "0.11",
            [(ago(120), money(9600), "Quotazione concessionario")],
        )
        self.add_vehicle("Honda SH 350i", "motorcycle", date_(2024, 4, 12), money(5900), "0.10")

        # Gold coins: some already owned, one more bought from the savings account.
        self.add_metal(
            "Sterline d'oro",
            "gold",
            "coin",
            "0.9167",
            [
                ("buy", ago(110), "15.96", Decimal("1.06"), None),
                ("buy", month_day(1, 22), "7.98", Decimal("1.06"), "deposito"),
            ],
        )
        # Inherited jewellery: weight known, cost unknown (a gift has no price).
        self.add_metal(
            "Gioielli in oro 18 kt",
            "gold",
            "jewelry",
            "0.75",
            [("buy", ago(140), "32.4", None, None)],
        )
        # Silver bars: VAT makes them dear to buy; one sale at roughly melt value.
        self.add_metal(
            "Lingotti d'argento",
            "silver",
            "bullion",
            "0.999",
            [
                ("buy", ago(100), "500", Decimal("1.25"), None),
                ("buy", month_day(3, 9), "250", Decimal("1.25"), "intesa"),
                ("sell", month_day(5, 12), "100", Decimal("0.97"), "intesa"),
            ],
        )

    def goals(self) -> None:
        emergency = SavingsGoal(
            user_id=self.user.id,
            name="Fondo di emergenza",
            kind="emergency_fund",
            priority=0,
            target_mode="months_of_primary_expenses",
            target_months=Decimal(6),
        )
        long_term = SavingsGoal(
            user_id=self.user.id,
            name="Investimenti a lungo termine",
            kind="long_term",
            priority=1,
            target_mode="open_ended",
        )
        self.db.add_all([emergency, long_term])
        self.db.flush()
        self.db.add_all(
            [
                SavingsGoalSource(goal_id=emergency.id, account_id=self.acc["deposito"].id),
                SavingsGoalSource(goal_id=long_term.id, account_id=self.acc["directa"].id),
            ]
        )

    # -- P.IVA forfettaria ---------------------------------------------------

    def flat_rate(self) -> None:
        """
        Invoices since ACTIVITY_START, a "Conto Tasse" that receives the suggested share
        of each collection and pays the F24s, and every F24 already due paid in full.

        Most of the story predates the six-month window, where no account has history:
        invoices collected before it have no income movement, and the provision they fed
        is the tax account's opening balance (minus any F24 paid before the window).
        """
        settings_row = flat_rate_service.get_or_create_settings(self.db, self.user)
        settings_row.activity_start_date = ACTIVITY_START
        for year in range(ACTIVITY_START.year, self.today.year + 1):
            flat_rate_service.get_or_create_year(self.db, self.user, year)

        invoices = self.issue_invoices()
        ledger = flat_rate_service.load_ledger(self.db, self.user)
        payments = self.f24_schedule(ledger)

        def provision(invoice: Invoice) -> Decimal:
            # The app's own suggestion for the issue date: 55% in the first year, the
            # second year's rate until the first declaration, the steady one after it.
            rate = flat_rate_service.provision_rate_on(ledger, invoice.issue_date)
            return money(flat_rate_service.invoice_total(invoice) * rate)

        before = [i for i in invoices if i.collected_on and i.collected_on < self.start]
        within = [i for i in invoices if i.collected_on and i.collected_on >= self.start]
        opening = sum((provision(i) for i in before), Decimal(0)) - sum(
            (Decimal(p.amount) for p in payments if p.paid_on < self.start), Decimal(0)
        )
        if opening < 0:
            sys.exit("The provision before the window doesn't cover the F24s paid in it.")
        self.open_account("tasse", "Conto Tasse", "savings", "EUR", opening)
        self.db.add(FlatRateProvisionSource(user_id=self.user.id, account_id=self.acc["tasse"].id))

        for invoice in within:
            self.transfer(
                "intesa",
                "tasse",
                invoice.collected_on,
                provision(invoice),
                f"Accantonamento tasse fattura {invoice.number}",
                "Accantonamento tasse",
            )
        for payment in payments:
            if payment.paid_on >= self.start:
                leg = create_cash_leg(
                    self.db,
                    account=self.acc["tasse"],
                    amount=-Decimal(payment.amount),
                    currency=BASE_CURRENCY,
                    rate=Decimal(1),
                    on_date=payment.paid_on,
                    description=(
                        f"F24 {F24_TAX_LABELS[payment.component]} — "
                        f"{F24_KIND_LABELS[payment.kind]} {payment.fiscal_year}"
                    ),
                    category_id=self.cat["F24"].id,
                )
                payment.transaction_id = leg.id
            self.db.add(payment)
        self.db.flush()

    def issue_invoices(self) -> list[Invoice]:
        """
        One month's work invoiced on its last working day, collected 2–6 weeks later (or
        not yet). Fees grow month on month; past SPLIT_ABOVE the month is a retainer plus
        a project for another client.
        """
        rivalsa = {
            row.year: Decimal(row.rivalsa_rate)
            for row in self.db.query(FlatRateYear).filter(FlatRateYear.user_id == self.user.id)
        }
        numbers: dict[int, int] = defaultdict(int)
        invoices: list[Invoice] = []
        year, month, index = ACTIVITY_START.year, ACTIVITY_START.month, 0
        while True:
            issued = self.business_day(
                date_(year, month, calendar.monthrange(year, month)[1])
            )
            if issued > self.today:
                break
            target = (FIRST_MONTH_FEES + MONTHLY_GROWTH * index) * self.rng.uniform(0.9, 1.1)
            if target <= SPLIT_ABOVE:
                parts = [(FIRST_CLIENTS[index % len(FIRST_CLIENTS)], target)]
            else:
                parts = [
                    (RETAINER_CLIENT, target * 0.45),
                    (PROJECT_CLIENTS[index % len(PROJECT_CLIENTS)], target * 0.55),
                ]
            for client, fee in parts:
                numbers[year] += 1
                amount = money(round(fee / 10) * 10)
                rate = rivalsa[year]
                paid_by_client = self.business_day(
                    issued + timedelta(days=self.rng.randint(14, 42))
                )
                collected = paid_by_client if paid_by_client <= self.today else None
                invoice = Invoice(
                    user_id=self.user.id,
                    number=f"{numbers[year]}/{year}",
                    client=client,
                    issue_date=issued,
                    amount=amount,
                    rivalsa_rate=rate,
                    stamp_duty=flat_rate_service.auto_stamp_duty(amount, rate),
                    collected_on=collected,
                )
                if collected is not None and collected >= self.start:
                    # As collecting onto an account does: the income is the invoice's own.
                    total = flat_rate_service.invoice_total(invoice)
                    income = Transaction(
                        account_id=self.acc["intesa"].id,
                        category_id=self.cat["Fatture"].id,
                        amount=total,
                        currency=BASE_CURRENCY,
                        amount_base_currency=total,
                        exchange_rate=Decimal(1),
                        date=collected,
                        description=f"Fattura {invoice.number} — {client}",
                        type="income",
                        source="manual",
                    )
                    self.db.add(income)
                    self.db.flush()
                    invoice.transaction_id = income.id
                    invoice.owns_transaction = True
                self.db.add(invoice)
                invoices.append(invoice)
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
            index += 1
        self.db.flush()
        return invoices

    def f24_schedule(self, ledger: "flat_rate_service.Ledger") -> list[TaxPayment]:
        """
        Every F24 line due by today (30 June and 30 November), paid in full on its working
        day. Computed in order on the ledger itself, since each payment changes the next:
        INPS paid in a year is deducted from that year's tax base.
        """
        payments: list[TaxPayment] = []
        for year in range(ACTIVITY_START.year + 1, self.today.year + 1):
            for due in (date_(year, 6, 30), date_(year, 11, 30)):
                if due > self.today:
                    continue
                for line in flat_rate_service.deadlines(ledger, year, due):
                    owed = line.amount_due - line.amount_paid
                    if line.due_date != due or owed <= 0:
                        continue
                    payment = TaxPayment(
                        user_id=self.user.id,
                        paid_on=self.business_day(due),
                        fiscal_year=line.fiscal_year,
                        component=line.component,
                        kind=line.kind,
                        amount=owed,
                    )
                    ledger.payments.append(payment)
                    payments.append(payment)
        return payments

    # -- sanity -------------------------------------------------------------

    def check_balances(self) -> dict[str, tuple[Decimal, Decimal]]:
        """(final balance, lowest running balance) per account; a demo must not be overdrawn."""
        self.db.flush()
        rows = (
            self.db.query(Transaction.account_id, Transaction.date, func.sum(Transaction.amount))
            .filter(
                Transaction.account_id.in_([a.id for a in self.acc.values()]),
                Transaction.deleted_at.is_(None),
            )
            .group_by(Transaction.account_id, Transaction.date)
            .order_by(Transaction.date)
            .all()
        )
        per_account: dict[object, list[Decimal]] = defaultdict(list)
        for account_id, _day, net in rows:
            per_account[account_id].append(Decimal(net))
        result = {}
        for key, account in self.acc.items():
            running, lowest = Decimal(0), Decimal(0)
            for net in per_account[account.id]:
                running += net
                lowest = min(lowest, running)
            result[key] = (running, lowest)
        overdrawn = {k: v for k, v in result.items() if v[1] < 0}
        if overdrawn:
            detail = ", ".join(f"{k} (low {v[1]})" for k, v in overdrawn.items())
            sys.exit(f"The generated history overdraws: {detail}. Nothing was written.")
        return result


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Create a demo user with six months of history.")
    parser.add_argument("--reset", action="store_true", help="erase the demo user first")
    args = parser.parse_args(argv)

    if settings.environment == "production":
        sys.exit("Refusing to seed demo data with ENVIRONMENT=production.")

    with SessionLocal() as db:
        existing = db.query(User).filter(User.email == DEMO_EMAIL).first()
        if existing is not None:
            if not args.reset:
                sys.exit(f"{DEMO_EMAIL} already exists. Use --reset to recreate it.")
            erase_user(db, existing.id)
            db.flush()

        user = User(
            email=DEMO_EMAIL,
            password_hash=hash_password(DEMO_PASSWORD),
            base_currency=BASE_CURRENCY,
            first_name="Demo",
            last_name="Utente",
            date_of_birth=date_(1991, 5, 14),
            work_type="flat_rate",
            approval_status="approved",
            email_verified_at=datetime.now(UTC),
        )
        db.add(user)
        db.flush()

        seeder = Seeder(db, user, date_.today())
        try:
            seeder.build()
            balances = seeder.check_balances()
        except BaseException:
            db.rollback()
            raise
        # The allocation plan is get-or-created on first read: nothing to seed.
        db.commit()
        ledger = flat_rate_service.load_ledger(db, user)
        position = flat_rate_service.tax_position(ledger, seeder.today)
        requirement = flat_rate_service.cash_requirement(ledger, seeder.today)
        invoice_count, payment_count = len(ledger.invoices), len(ledger.payments)

    print(f"Demo user ready: {DEMO_EMAIL} / {DEMO_PASSWORD}")
    print(f"History from {seeder.start} to {seeder.today}")
    for key, (final, lowest) in balances.items():
        account = seeder.acc[key]
        print(f"  {account.name:<22} {account.currency} {final:>12}  (lowest {lowest})")
    print(
        f"P.IVA: {invoice_count} invoices collected, {payment_count} F24 lines paid;"
        f" tax debt {position.debt}, credit {position.credit}, F24s still to pay {requirement}"
    )


if __name__ == "__main__":
    main()

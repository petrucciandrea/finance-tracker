# Finance Tracker

Personal finance tracker, built in phases:

1. **Phase 1 (done)** — expense tracker: accounts, categories, transactions, multi-currency, CSV import
2. **Phase 2 (archived)** — budgeting: spending limits per category, current + historical status.
   The UI is archived — no nav link and no `/budgets` route — but `BudgetsPage`, its hooks/API
   client, the backend router and the data are all untouched. Re-enable by restoring the route.
3. **Phase 3 (done)** — portfolio tracker: stocks/ETFs/crypto, price sync jobs, net-worth view
4. **Phase 4 (done)** — planning engine: necessity taxonomy, 50/25/15/10 allocation model,
   survival budget, cut simulator, waterfall savings ladder with executable giroconti
5. **Physical assets** — vehicles (depreciation + manual valuations) and precious metals
   (fractional positions: grams × purity × spot), counted in net worth on the "Beni" page
6. **Work profile** — `users.work_type` (employee / P.IVA forfettaria / ordinaria) in the
   profile's "Lavoro" section. Only `flat_rate` unlocks a section so far ("Fatture"):
   invoices issued → collected, taxes and INPS on a cash basis, F24 deadlines and payments,
   the suggested provision rate, and the accounts/holdings the provision sits in

Single-user-per-account app; multi-user capable but built for personal use.

## Stack

- **Backend**: FastAPI + SQLAlchemy 2.0 + PostgreSQL 16, Alembic migrations, Poetry
- **Frontend**: React 19 + TypeScript + Vite + Tailwind CSS v4, TanStack Query, React Router, React Hook Form + Zod
- **Infra**: Docker Compose (`db`, `db_test`, `backend`, `frontend`)
- **Tests**: pytest + httpx TestClient against a dedicated Postgres test DB

## Layout

```
finance-tracker/
├── docker-compose.yml
├── Makefile                  # all common commands live here
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── .env                  # gitignored; .env.example is the template
│   ├── alembic/
│   │   ├── env.py            # reads DB URL from app settings, not alembic.ini
│   │   └── versions/
│   ├── app/
│   │   ├── main.py           # app factory, CORS, exception handlers, router mounting
│   │   ├── deps.py           # get_db, get_current_user
│   │   ├── core/
│   │   │   ├── config.py     # Pydantic Settings
│   │   │   └── security.py   # password hashing, JWT create/decode
│   │   ├── db/session.py     # engine + SessionLocal
│   │   ├── models/           # SQLAlchemy models (__init__.py + asset_transaction.py,
│   │   │                     # physical_asset.py, flat_rate.py, refresh_token.py)
│   │   ├── schemas/          # Pydantic schemas (all in __init__.py)
│   │   ├── routers/          # auth, accounts, categories, transactions, budgets,
│   │   │                     # planning, savings_goals, portfolio, physical_assets,
│   │   │                     # flat_rate
│   │   └── services/         # exchange_rates, csv_import, asset_prices, net_worth,
│   │                         # necessity, planning, waterfall, transfers, periods,
│   │                         # ownership, physical_assets, flat_rate
│   └── tests/
└── frontend/
    └── src/
        ├── api/              # one module per resource + client.ts (axios + JWT)
        ├── types/index.ts    # mirrors backend Pydantic schemas
        ├── hooks/            # TanStack Query wrappers per resource
        ├── context/          # AuthContext
        ├── components/layout/
        └── pages/
```

## Commands

Always run from the repo root:

```bash
make up            # start all services
make down          # stop all services
make logs          # tail backend logs
make test          # migrate test DB, then run pytest
make test-reset-db # wipe + recreate the test DB (use when it gets inconsistent)
make migrate       # alembic upgrade head (dev DB)
make lint          # ruff + mypy
make shell-db      # psql into the dev DB
```

Never run `pytest` directly — `make test` applies migrations to `db_test` first, which the bare command skips.

## Design decisions (and why)

Things that look odd but are deliberate. Don't "fix" them without reading this.

### Money is Decimal/Numeric, never float
`Numeric` in models, `Decimal` in schemas, string in the JSON API. Float rounding errors are unacceptable in a finance app.

### Multi-currency: exchange rates are frozen at write time
Each transaction stores `amount`, `currency`, plus `amount_base_currency` and `exchange_rate` computed **at creation and never recomputed**. Recomputing on read would make last year's reports change every day. Live rates are only used for phase-3 portfolio valuation.

`update_transaction` recomputes the conversion **only** when `amount` or `date` change — editing a description must not touch the frozen rate.

### Soft delete everywhere
`accounts`, `categories`, `transactions`, `budgets` set `deleted_at` instead of deleting rows. Every query must filter `deleted_at IS NULL`. Transactions keep their FK to a deleted account/category on purpose — the frontend renders "deleted" rather than breaking history.

Categories are the exception to the "just soft-delete it" rule: deleting one that still has active subcategories returns 409, since a truncated hierarchy is worse to render than one orphaned FK.

### Closed accounts are not deleted accounts
`accounts.closed_at` (a `DATE`, set/cleared by PATCH) marks an account as closed. Unlike
`deleted_at` it keeps the account in lists, balances and net worth. It only refuses
movements dated **after** the close (409, via `ownership.ensure_account_open_on`, also
called by `create_linked_transfer` / `create_cash_leg`; CSV previews flag such rows
unparsable). Back-dated fixes still go through.

Closing is refused before the last movement's date, in the future, or while the account
funds a goal. A non-zero balance is **not** refused — it stays in the totals rather than
silently vanishing; the UI warns instead.

### Every expense/income transaction has a category
If no `category_id` is supplied, the backend assigns (creating on first use) a **"Varie"** category of the matching type. Applies to manual creation, CSV import, and PATCH that clears the category. `type: transfer` is exempt — a transfer between your own accounts isn't a categorizable spend.

### Refresh tokens are stored and rotated
`refresh_tokens` holds a SHA-256 hash of each issued refresh token. `/auth/refresh` revokes the used token and issues a new pair, so a stolen refresh token is single-use. This is what makes `/auth/logout` a real revocation rather than a client-side forget.

JWTs include a `jti` (random UUID) because `iat`/`exp` are second-resolution — without it, two tokens issued in the same second are byte-identical and collide on the `token_hash` unique index.

### Login leaks nothing about which emails exist
Unknown email and wrong password both return the same 401 with the same message. Don't "improve" the error message.

### Query-parameter models need `Annotated[..., Query()]`
```python
params: Annotated[TransactionListParams, Query()]   # correct
params: TransactionListParams = Depends()            # generates a request body on a GET
```
Also: don't use `default_factory` on list fields in these models — FastAPI passes the factory object through instead of resolving it. Use `| None = None` and apply the default inside the handler.

### Read aggregate query results via `row._mapping`
`getattr(row, "category_id", None)` silently returns `None` when the label collides with a real column name elsewhere in the join. `row._mapping["category_id"]` is unambiguous.

### Budget periods are calendar-based
`monthly` = calendar month, `yearly` = calendar year, regardless of `start_date`. `start_date` only bounds the start: a budget created mid-month doesn't count spend from before it existed. `GET /budgets/status?date=YYYY-MM-DD` serves both current and historical periods — there is no separate history endpoint.

Budgets can only be set on **expense** categories (422 otherwise).

### Necessity taxonomy: nullable, inherited, never backfilled
`categories.necessity_level` (primary/useful/discretionary, **expense only**) and
`transactions.necessity_level_override` (**expense only**). Effective level is
`COALESCE(override, category.necessity_level, parent.necessity_level)` — both joins
LEFT, since `category_id` is nullable.

Existing rows start NULL and are reported as an explicit `unclassified` bucket with a
coverage percentage. Backfilling them to `primary` would produce a survival budget and
an emergency-fund target that look plausible and are wrong.

`categories.excluded_from_income_base` (**income only**) keeps refunds and reversals out
of the allocation model's denominator — CSV import types rows by sign alone, so they all
arrive as `income`.

### The allocation plan is mutable; budgets are not
`allocation_plans` is get-or-created with the 50/25/15/10 preset on first read, and has
**no unique index on `user_id`** on purpose: that would turn two concurrent first reads
into a 500, whereas the "Varie" get-or-create stays soft because a duplicate row is
harmless. The oldest surviving row wins.

Editing the percentages *should* change how the current period reads — a plan is
prospective, unlike a budget, which is a historical commitment. The four percentages move
together (the DB constrains them to sum to 100).

### An unknown average is `None`, never `0`
`average_monthly_primary_expenses` returns `None` when there isn't one complete month of
history. Zero would claim the user needs nothing to live on — and would mark a dynamic
emergency-fund target as already met, releasing the whole savings quota to the next rung.
Averages ignore the month in progress and count only whole months.

### Waterfall: priority order, 95% band, downward roll-up
The savings quota fills rungs in `priority` order and spills into the next only when the
one above is full. A drained emergency fund refills itself for free — its gap reopens and
it is top priority again. A rung counts as funded at **95%**: without the band a dynamic
target starves the ladder forever with micro top-ups.

No unique index on `(user_id, priority)` — Postgres checks per statement and the ORM
updates row by row, so swapping two priorities always collides. Order is
`(priority, created_at)`.

An account funds **at most one goal** and there is **at most one open-ended rung**; both
are router-enforced 409s, since neither rule's scope fits a unique index on its table.
Deleting an account that funds a goal is a 409 too — it would vanish from the balance map
and the goal would silently read as unfunded.

Sources are accounts only. An asset source would put a live price + FX call per position
behind a plain GET.

### A transfer MAY have a counterpart
`transactions.counterpart_transaction_id` pairs the two legs of a giroconto. Every opening
balance and portfolio cash leg still has NULL there, so nothing may assume a transfer is
paired. Deleting one leg retires both plus its `savings_allocations` row; editing one
leg's `amount`/`date` is a 409.

Linked pairs come from `services/transfers.py:create_linked_transfer`, called by the waterfall
execute endpoint and by `POST /transactions/transfers` (the manual giroconto form). A plain
`POST /transactions` with `type: transfer` still writes a single unpaired row.

A linked pair is listed as one row (`merge_transfer_legs` hides the incoming leg), so a
PATCH of `description` or `category_id` on either leg is mirrored onto the other. A
transfer's category is optional and must be `transfer`-type — never "Varie". A portfolio
buy/sell takes the same optional `category_id` for its cash leg (create only; later edits
go through the transaction itself).

Giroconti are **same-currency only** (422 otherwise): converting means calling `get_rate`
inside a multi-row write.

### Budgets roll up subcategories
A budget on a parent counts its children's spend — matching `category_id` exactly meant a
budget on "Casa" reported zero while everything sat under "Affitto". Roll-up is downward
only. One active budget per `(category, period)`, enforced by a partial unique index.

### Cache services never commit the caller's session
`get_rate` / `get_price` and their history variants `flush()` and leave the transaction to
the caller. They used to commit outright, so a cache miss halfway through a multi-row
write persisted a half-finished state. The cost: a read-only endpoint must commit if it
wants a fetched rate to stick — `/holdings`, `/net-worth` and `/history` do so explicitly.

**Resolve every rate before the first `db.add()`** in any handler that writes more than
one row.

### Physical assets: in net worth, never in cash
`physical_assets` holds vehicles and precious metals (CHECK constraints keep each kind's
columns apart). They add to `total_net_worth` and the history chart, but never to
`total_cash_balance` — a car or a gold bar doesn't extend the survival budget's runway or
fund a waterfall rung.

- **Vehicles** are one object, bought and sold whole (`/sell`, `/unsell`; purchase and
  sale live on the row). They depreciate at `depreciation_rate` per year, compounded daily
  from an anchor: the purchase, or the latest `physical_asset_valuations` row on or before
  the date. A valuation re-anchors the curve, it doesn't freeze the value.
- **Metals** are a *position*, bought into and sold from by the gram: weight, prices and
  dates live in `physical_asset_movements` (buy/sell), and the row's purchase/sale columns
  are NULL by CHECK. Creating a metal records its first buy; prices are edited through the
  movements (a PATCH of `purchase_price` on a metal is 422), while a PATCH of
  `purchase_date` re-dates the first buy — ledger re-walked, rate reconverted, cash leg
  moved, closed-account rule applied. Cost is weighted-average, in
  base currency, as in `compute_holding_positions`; a buy with no price (a gift) makes the
  held grams' cost unknown (`None`) until the position is emptied. Every write re-walks the
  would-be ledger and refuses one that sells grams not held on that date — including
  deleting a buy that a later sale relied on. The only movement can't be deleted (delete
  the asset). An emptied position reads as sold (`sold_at` = last sale).
- Value = grams held × purity × spot. Jewellery too: workmanship has no dependable resale
  market, so melt value is the honest estimate. Spot comes from Yahoo
  `GC=F`/`SI=F`/`PL=F` (USD per troy ounce, ÷ 31.1034768 for grams) through seeded
  `assets` rows with `asset_type = 'metal'`, so the `asset_prices` cache and history
  backfill apply unchanged. `metal` is deliberately not in the API's `AssetType` enum.
- An unavailable quote makes `current_value_base_currency` `None`, never `0`, and
  the net-worth total skips it rather than 500ing.
- Paying for a purchase (or collecting a sale) from an account is optional and writes a
  one-sided `transfer` via `services/transfers.py:create_cash_leg` — the same helper the
  portfolio's buy/sell cash leg uses. Same-currency only (422 otherwise). Editing a
  vehicle's price/date moves its leg; deleting an asset or a movement retires its legs.

### P.IVA forfettaria: cash basis, frozen years, two different debts
Everything filters on `invoices.collected_on`, never the issue date: an invoice issued in
December and paid in January is taxed in January's year (and listed under both).

Revenue = fee + rivalsa INPS 4% + €2 bollo charged to the client (both are revenue; the
bollo since AdE 428/2022; due above €77.47 of fee + rivalsa). Base = revenue × coefficient;
INPS = base × rate; imposta = (base − INPS **paid** in the year) × rate. The deduction comes
from the recorded F24s, so a per-invoice figure can't apply it and stays gross (safe side).
Advances (metodo storico): 100% of the tax (none ≤ €51.65, one November payment < €257.52,
else 40/60) + 80% of INPS (40/40).

`flat_rate_years` freezes the parameters per year, like exchange rates on transactions: the
INPS rate changes yearly. A new year copies the previous one, except the two per-year
choices: `provision_rate` restarts on the suggestion and `substitute_tax_rate` on automatic.
A NULL `substitute_tax_rate` is **automatic**: 5% for the start year and the four after it,
15% after, from `flat_rate_settings.activity_start_date` (15% without one). A value is an
override for someone who doesn't meet the 5%'s other conditions. Never copy an explicit 5%
forward — past the fifth year it would be wrong. Unique on `(user, year)`
with `INSERT … ON CONFLICT DO NOTHING`, unlike `allocation_plans`: a duplicate year row
would change the year's numbers, not just be harmless.

Two debts, on purpose — don't merge them:
- `tax_liability`: accrued on collected income minus every payment. **This** is what net
  worth and `/history` subtract. Advances paid ahead of the income make it negative (a
  credit). Counting next year's advances as debt would understate net worth by ~20% of
  first-year income until next year's income absorbed them.
- `cash_requirement`: everything the F24s will still ask for income collected so far,
  next year's advances included. The provision is compared against this (the "gap").

The suggested provision rate is computed, not a fixed menu: each euro owes its year's load
plus next year's advances on it, minus the share this year's advances (funded from last
year) already prepay, spread over last year's revenue annualised on its months of activity.
That reproduces 55% → 40% → 30% for a June start at 78%/5%/26.23% with the 15% margin.

Collecting either links an existing income (`owns_transaction = false`, typically from
CSV) or writes one (`true`); only an owned one is retired by uncollect/delete, and its
amount follows the invoice. F24 payments write a one-sided `transfer` via
`create_cash_leg`, not an expense: the cost was booked as a liability when the income
came in, so paying it moves cash and debt together and net worth doesn't jump. The
transactions router refuses amount/date edits on those legs and deleting any linked one.

Provision sources are `(account)` = its cash, or `(account, asset)` = that holding. An
account source is earmarked: it can't fund a savings goal (409 both ways), can't be
deleted (409), and its balance is left out of the survival budget's runway.

The planning engine runs on income **net** of flat-rate taxes (`planning.income_base`):
gross income minus imposta + INPS on the invoices collected in the period. It feeds the
50/25/15/10 buckets, the savings residual, the waterfall quota, the simulator and the
survival budget's monthly income. Without it the State's ~24% read as savings, since F24s
are transfers and never spend. The per-invoice estimate is used (`flat_rate.tax_cost`), not
the provision rate: next year's advances are a prepayment, not a cost, and the year's own
figure would swing negative in the month an F24 lowers the tax via the INPS deduction.

`users.work_type` only gates the UI. The API and the liability work regardless — turning
the section off must not make a real debt vanish from net worth.

### CSV import is two-step, preview lives in memory
`POST /transactions/import` parses and returns a preview with per-row flags (`is_parsable`, `is_duplicate`); `POST /transactions/import/confirm` commits only the selected rows. The preview is held in a process-local dict with a 15-minute TTL — **this breaks with more than one backend replica**. Move it to Redis before scaling out, not to a DB table.

Duplicate detection is a heuristic (same account + date + amount + currency); the user makes the final call in the preview.

### Exchange rate source
Frankfurter, at `https://api.frankfurter.dev/v1` (the old `.app` domain 301-redirects; `httpx` needs `follow_redirects=True`). Fiat only — phase 3 crypto needs a different source. Rates are cached per `(from, to, date)` in `exchange_rates`.

## Testing

- Each test runs inside a transaction that's rolled back afterwards — no manual cleanup, no cross-test leakage.
- The session joins it with `join_transaction_mode="create_savepoint"`, so a handler's own
  `commit()`/`rollback()` acts on a SAVEPOINT. Without it a handler's commit looked like a
  no-op and its rollback tore down the test — which is how a non-atomic batch endpoint went
  unnoticed.
- `get_db` is overridden so requests made through `TestClient` see the test's own session.
- Exchange rate lookups are monkeypatched in cross-currency tests; tests never hit the network.
  Monkeypatch binds to the **import site**: holding valuation reads `get_rate` from
  `services/net_worth.py`, while the portfolio router converts its own cash leg — patch
  whichever one the code under test actually goes through.
- `db_test` uses a named volume. If it ever ends up with `alembic_version` present but no tables (Alembic thinks it's migrated, so `upgrade head` does nothing), run `make test-reset-db`.

## Frontend conventions

- Access token lives in memory only; refresh token in `localStorage`. On page load `AuthContext` silently exchanges the refresh token for a new pair before rendering protected routes.
- The axios interceptor retries a 401 once after refreshing, and **queues** concurrent requests during an in-flight refresh — firing parallel refreshes would race against backend rotation and fail.
- Mutations invalidate the whole resource query key rather than hand-patching the cache. Fine at this scale.
- Amounts arrive as strings (Decimal) — `Number()` them only for display math.
- The transaction form takes a positive number; the sign is applied from `type` (expense → negative) on submit.
- "Nascondi importi" (`users.hide_amounts`, PATCH `/auth/me`) is masked inside `lib/format.ts`
  (`formatAmount`/`formatMoney`/`formatCompact`/`formatQuantity`), so new call sites get it for
  free — never format an amount around them. The flag is module state set by `AuthProvider`;
  `AppLayout` re-keys the `<Outlet>` on toggle so already-rendered pages pick it up.
  Percentages stay visible. Input fields in edit forms show raw values on purpose.

## Conventions

- Comments explain **why**, not what. If a line looks wrong but isn't, say why it's there.
- New domain routers follow `accounts.py`: a `_get_owned_*` helper that enforces ownership + soft-delete filter in one place, used by every handler that touches a single row.
- Aggregations go in SQL (`GROUP BY`), not Python.
- API errors use the `{"error": {"code", "message", "details"}}` envelope from `main.py`'s handlers.
- Frontend types in `types/index.ts` are hand-maintained against the Pydantic schemas — update both together.

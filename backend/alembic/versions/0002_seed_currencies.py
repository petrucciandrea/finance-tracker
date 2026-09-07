"""seed currencies

Revision ID: 0002_seed_currencies
Revises: 756e0a81c20a
Create Date: 2026-09-06

Data-only migration: populates the `currencies` reference table.
Run after the initial schema migration that creates the `currencies` table
(accounts/transactions/assets/exchange_rates all FK into this table, so it
must be seeded before any of those rows can be created).
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0002_seed_currencies"
down_revision = "756e0a81c20a"
branch_labels = None
depends_on = None


# Minimal reusable table definition — enough for bulk_insert/delete,
# doesn't need to match the full model (no FKs/constraints required here).
currencies_table = sa.table(
    "currencies",
    sa.column("code", sa.String),
    sa.column("name", sa.String),
    sa.column("symbol", sa.String),
    sa.column("decimal_places", sa.Integer),
)

CURRENCIES = [
    {"code": "EUR", "name": "Euro", "symbol": "€", "decimal_places": 2},
    {"code": "USD", "name": "US Dollar", "symbol": "$", "decimal_places": 2},
    {"code": "GBP", "name": "British Pound", "symbol": "£", "decimal_places": 2},
    {"code": "CHF", "name": "Swiss Franc", "symbol": "CHF", "decimal_places": 2},
    {"code": "JPY", "name": "Japanese Yen", "symbol": "¥", "decimal_places": 0},
    {"code": "BTC", "name": "Bitcoin", "symbol": "₿", "decimal_places": 8},
    {"code": "ETH", "name": "Ethereum", "symbol": "Ξ", "decimal_places": 8},
]


def upgrade() -> None:
    op.bulk_insert(currencies_table, CURRENCIES)


def downgrade() -> None:
    codes = [c["code"] for c in CURRENCIES]
    conn = op.get_bind()
    conn.execute(
        currencies_table.delete().where(currencies_table.c.code.in_(codes))
    )

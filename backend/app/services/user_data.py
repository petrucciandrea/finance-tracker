"""
Everything a user owns, in one place: used both to erase an account (GDPR art.
17) and to export it (art. 20).

One ordered registry serves both, so the two can't drift apart. The order is
children first: the foreign keys have no ON DELETE CASCADE, so a parent row
can only go once whatever points at it is gone. Self-references
(transactions.counterpart_transaction_id, categories.parent_id) are fine
because each table is deleted in a single statement.

`tests/test_user_data.py` compares this registry with the metadata, so a new
table that isn't classified here fails the suite instead of silently surviving
an account deletion.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

_BY_USER = "user_id = :uid"
_OF_ACCOUNTS = "account_id IN (SELECT id FROM accounts WHERE user_id = :uid)"
_OF_ASSETS = "physical_asset_id IN (SELECT id FROM physical_assets WHERE user_id = :uid)"

# (table, WHERE clause scoped to the user), children first.
OWNED_TABLES: list[tuple[str, str]] = [
    ("savings_allocations", _BY_USER),
    ("savings_goal_sources", "goal_id IN (SELECT id FROM savings_goals WHERE user_id = :uid)"),
    ("savings_goals", _BY_USER),
    ("flat_rate_provision_sources", _BY_USER),
    ("tax_payments", _BY_USER),
    ("invoices", _BY_USER),
    ("flat_rate_years", _BY_USER),
    ("flat_rate_settings", _BY_USER),
    ("physical_asset_movements", _OF_ASSETS),
    ("physical_asset_valuations", _OF_ASSETS),
    ("physical_assets", _BY_USER),
    ("asset_transactions", _OF_ACCOUNTS),
    ("allocation_plans", _BY_USER),
    ("budgets", _BY_USER),
    ("transactions", _OF_ACCOUNTS),
    ("categories", _BY_USER),
    ("accounts", _BY_USER),
    ("refresh_tokens", _BY_USER),
]

# Shared reference/cache data, not about any user: currencies, FX rates, the
# asset catalogue and its price history are filled from public sources and
# serve everyone.
GLOBAL_TABLES = {"currencies", "exchange_rates", "assets", "asset_prices"}

# Left out of the export: they authenticate the account rather than describe
# the person, and handing them over would only widen what a leaked file exposes.
_EXPORT_SKIP_TABLES = {"refresh_tokens"}
_EXPORT_SKIP_USER_COLUMNS = {"password_hash"}


def erase_user(db: Session, user_id: UUID) -> None:
    """Hard-delete the user and everything they own, soft-deleted rows included.

    The soft-delete rule ("never really remove a row") is the one thing erasure
    overrides: a person asking to be forgotten gets forgotten. Does not commit.
    """
    for table, where in OWNED_TABLES:
        db.execute(text(f"DELETE FROM {table} WHERE {where}"), {"uid": user_id})  # noqa: S608
    db.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user_id})


def _jsonable(value: Any) -> Any:
    # Money stays a string, as everywhere in the API: a JSON number would be
    # parsed as a float by most readers.
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


def export_user(db: Session, user_id: UUID) -> dict[str, Any]:
    """Every row the user owns, soft-deleted ones too, as plain JSON-able data."""
    params = {"uid": user_id}

    user_row = db.execute(text("SELECT * FROM users WHERE id = :uid"), params).mappings().one()
    user = {
        key: _jsonable(value)
        for key, value in user_row.items()
        if key not in _EXPORT_SKIP_USER_COLUMNS
    }

    tables: dict[str, list[dict[str, Any]]] = {}
    for table, where in reversed(OWNED_TABLES):  # parents first reads better
        if table in _EXPORT_SKIP_TABLES:
            continue
        rows = db.execute(text(f"SELECT * FROM {table} WHERE {where}"), params).mappings()  # noqa: S608
        tables[table] = [{k: _jsonable(v) for k, v in row.items()} for row in rows]

    return {"exported_at": datetime.now().astimezone().isoformat(), "user": user, "data": tables}

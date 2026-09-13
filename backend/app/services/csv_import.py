"""
CSV import: parse -> preview -> confirm.

Design choice: preview data lives in a short-lived in-memory store (dict),
not the DB. It's not "real" data until the user confirms it, and for a
single-instance personal project this avoids adding a throwaway DB table
just to hold data for a few minutes.

Trade-off to know about: this store is per-process and not persisted, so it
won't survive an app restart or work behind multiple backend replicas. If
you ever deploy with more than one instance, move this to Redis (same TTL
idea, `SETEX import:{id} 900 <json>`) instead of adding a Postgres table.
"""

import csv
import io
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from datetime import date as date_
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import Asset, AssetTransaction, Transaction

_PREVIEW_TTL = timedelta(minutes=15)
_preview_store: dict[UUID, "ImportPreviewData"] = {}
_asset_preview_store: dict[UUID, "AssetImportPreviewData"] = {}


@dataclass
class ImportRow:
    row_number: int
    account_id: UUID
    date: date_
    amount: Decimal
    currency: str
    description: str | None
    suggested_category_id: UUID | None = None
    is_duplicate: bool = False
    is_parsable: bool = True
    error: str | None = None


@dataclass
class ImportPreviewData:
    import_id: UUID
    account_id: UUID
    rows: list[ImportRow]
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def _is_expired(created_at: datetime) -> bool:
    return datetime.now(UTC) - created_at > _PREVIEW_TTL


def _parse_row(row_number: int, account_id: UUID, raw: dict[str, str]) -> ImportRow:
    """
    Expects columns: date (YYYY-MM-DD), amount, currency, description.
    Adjust this mapping per-bank if you end up supporting multiple export
    formats — that's the part that will actually vary, everything else
    (dedup, preview/confirm flow) stays the same.
    """
    try:
        parsed_date = date_.fromisoformat(raw["date"].strip())
        amount = Decimal(raw["amount"].strip())
        currency = raw["currency"].strip().upper()
        description = raw.get("description", "").strip() or None
        return ImportRow(
            row_number=row_number,
            account_id=account_id,
            date=parsed_date,
            amount=amount,
            currency=currency,
            description=description,
        )
    except (KeyError, ValueError, InvalidOperation) as exc:
        return ImportRow(
            row_number=row_number,
            account_id=account_id,
            date=date_.today(),
            amount=Decimal("0"),
            currency="",
            description=None,
            is_parsable=False,
            error=str(exc),
        )


def _mark_duplicates(db: Session, rows: list[ImportRow]) -> None:
    """
    A row is flagged as a likely duplicate if an existing, non-deleted
    transaction on the same account matches on (date, amount, currency).
    Heuristic, not a guarantee — the user makes the final call in the preview.
    """
    for row in rows:
        if not row.is_parsable:
            continue
        exists = (
            db.query(Transaction)
            .filter(
                Transaction.account_id == row.account_id,
                Transaction.date == row.date,
                Transaction.amount == row.amount,
                Transaction.currency == row.currency,
                Transaction.deleted_at.is_(None),
            )
            .first()
        )
        row.is_duplicate = exists is not None


def parse_csv(db: Session, account_id: UUID, file_content: bytes) -> ImportPreviewData:
    text = file_content.decode("utf-8-sig")  # handles Excel's BOM-prefixed exports
    reader = csv.DictReader(io.StringIO(text))

    rows = [
        _parse_row(i, account_id, raw) for i, raw in enumerate(reader, start=1)
    ]
    _mark_duplicates(db, rows)

    preview = ImportPreviewData(import_id=uuid.uuid4(), account_id=account_id, rows=rows)
    _preview_store[preview.import_id] = preview
    return preview


def get_preview(import_id: UUID) -> ImportPreviewData | None:
    preview = _preview_store.get(import_id)
    if preview is None:
        return None
    if _is_expired(preview.created_at):
        _preview_store.pop(import_id, None)
        return None
    return preview


def discard_preview(import_id: UUID) -> None:
    _preview_store.pop(import_id, None)


# ---------------------------------------------------------------------------
# Asset transactions (portfolio buy/sell ledger) — same parse -> preview ->
# confirm shape as above, but a separate preview store: the two flows import
# different models (Transaction vs. AssetTransaction) so keeping the stores
# apart avoids a row from one ever being confused for the other's.
# ---------------------------------------------------------------------------

@dataclass
class AssetImportRow:
    row_number: int
    account_id: UUID
    symbol: str
    asset_type: str
    type: str
    quantity: Decimal
    price: Decimal
    fee: Decimal
    date: date_
    notes: str | None
    is_duplicate: bool = False
    is_parsable: bool = True
    error: str | None = None


@dataclass
class AssetImportPreviewData:
    import_id: UUID
    account_id: UUID
    rows: list[AssetImportRow]
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def _parse_asset_row(row_number: int, account_id: UUID, raw: dict[str, str]) -> AssetImportRow:
    """
    Expects columns: symbol, asset_type, type, quantity, price, fee, date,
    notes (fee/notes optional).
    """
    try:
        symbol = raw["symbol"].strip().upper()
        if not symbol:
            raise ValueError("symbol is required")

        asset_type = raw["asset_type"].strip().lower()
        if asset_type not in ("stock", "etf", "crypto"):
            raise ValueError(f"asset_type must be stock/etf/crypto, got {asset_type!r}")

        transaction_type = raw["type"].strip().lower()
        if transaction_type not in ("buy", "sell"):
            raise ValueError(f"type must be buy/sell, got {transaction_type!r}")

        quantity = Decimal(raw["quantity"].strip())
        price = Decimal(raw["price"].strip())
        if quantity <= 0 or price <= 0:
            raise ValueError("quantity and price must both be positive")

        fee = Decimal(raw.get("fee", "").strip() or "0")
        parsed_date = date_.fromisoformat(raw["date"].strip())
        notes = raw.get("notes", "").strip() or None

        return AssetImportRow(
            row_number=row_number,
            account_id=account_id,
            symbol=symbol,
            asset_type=asset_type,
            type=transaction_type,
            quantity=quantity,
            price=price,
            fee=fee,
            date=parsed_date,
            notes=notes,
        )
    except (KeyError, ValueError, InvalidOperation) as exc:
        return AssetImportRow(
            row_number=row_number,
            account_id=account_id,
            symbol="",
            asset_type="stock",
            type="buy",
            quantity=Decimal("0"),
            price=Decimal("0"),
            fee=Decimal("0"),
            date=date_.today(),
            notes=None,
            is_parsable=False,
            error=str(exc),
        )


def _mark_asset_duplicates(db: Session, rows: list[AssetImportRow]) -> None:
    """
    Heuristic, same spirit as `_mark_duplicates`: same account + asset + type
    + date + quantity + price. The asset may not exist in the DB yet (a
    never-before-seen symbol can't collide with anything), so this is a plain
    read — no asset gets created during preview.
    """
    for row in rows:
        if not row.is_parsable:
            continue
        exists = (
            db.query(AssetTransaction)
            .join(Asset, Asset.id == AssetTransaction.asset_id)
            .filter(
                AssetTransaction.account_id == row.account_id,
                Asset.symbol == row.symbol,
                Asset.asset_type == row.asset_type,
                AssetTransaction.type == row.type,
                AssetTransaction.date == row.date,
                AssetTransaction.quantity == row.quantity,
                AssetTransaction.price == row.price,
                AssetTransaction.deleted_at.is_(None),
            )
            .first()
        )
        row.is_duplicate = exists is not None


def parse_asset_csv(db: Session, account_id: UUID, file_content: bytes) -> AssetImportPreviewData:
    text = file_content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

    rows = [_parse_asset_row(i, account_id, raw) for i, raw in enumerate(reader, start=1)]
    _mark_asset_duplicates(db, rows)

    preview = AssetImportPreviewData(import_id=uuid.uuid4(), account_id=account_id, rows=rows)
    _asset_preview_store[preview.import_id] = preview
    return preview


def get_asset_preview(import_id: UUID) -> AssetImportPreviewData | None:
    preview = _asset_preview_store.get(import_id)
    if preview is None:
        return None
    if _is_expired(preview.created_at):
        _asset_preview_store.pop(import_id, None)
        return None
    return preview


def discard_asset_preview(import_id: UUID) -> None:
    _asset_preview_store.pop(import_id, None)
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
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from datetime import date as date_
from decimal import Decimal, InvalidOperation
from uuid import UUID

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.models import Asset, AssetTransaction, Currency, Transaction

_PREVIEW_TTL = timedelta(minutes=15)
MAX_CSV_BYTES = 2 * 1024 * 1024
MAX_CSV_ROWS = 5000
# Columns are Numeric(18, 8): anything at or above 1e10 would overflow at confirm
# time and lose the whole batch, so it is flagged per row in the preview instead.
_MAX_ABS_VALUE = Decimal("1e10")
# Yahoo/CoinGecko-style tickers. The symbol ends up in an outbound URL path, so
# anything outside this set ('/', '?', '#', '..') must never get that far.
SYMBOL_PATTERN = r"[A-Z0-9][A-Z0-9.\-=^]{0,19}"
_CURRENCY_PATTERN = re.compile(r"[A-Z]{3}")


class CsvImportError(ValueError):
    """The file as a whole can't be imported (as opposed to one bad row)."""


def read_upload(file: UploadFile) -> bytes:
    # One byte past the cap is enough to know it's too big without reading all of it.
    content = file.file.read(MAX_CSV_BYTES + 1)
    if len(content) > MAX_CSV_BYTES:
        raise CsvImportError(f"File too large (max {MAX_CSV_BYTES // (1024 * 1024)} MB)")
    return content


def _read_rows(file_content: bytes) -> list[dict[str, str]]:
    try:
        text = file_content.decode("utf-8-sig")  # handles Excel's BOM-prefixed exports
    except UnicodeDecodeError:
        raise CsvImportError("File must be UTF-8 encoded text") from None
    rows: list[dict[str, str]] = []
    try:
        for raw in csv.DictReader(io.StringIO(text)):
            if len(rows) >= MAX_CSV_ROWS:
                raise CsvImportError(f"Too many rows (max {MAX_CSV_ROWS})")
            rows.append(raw)
    except csv.Error as exc:
        raise CsvImportError(f"Malformed CSV: {exc}") from None
    return rows


def _decimal(value: str) -> Decimal:
    number = Decimal(value.strip())
    # NaN/Infinity parse as Decimals but break every comparison after this.
    if not number.is_finite() or abs(number) >= _MAX_ABS_VALUE:
        raise ValueError(f"number out of range: {value.strip()[:30]!r}")
    return number


def _evict_expired() -> None:
    # Expired previews were only dropped when someone asked for that exact id,
    # so abandoned uploads accumulated for the life of the process.
    for store in (_preview_store, _asset_preview_store):
        for key in [k for k, v in store.items() if _is_expired(v.created_at)]:
            del store[key]
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
        amount = _decimal(raw["amount"])
        currency = raw["currency"].strip().upper()
        if not _CURRENCY_PATTERN.fullmatch(currency):
            raise ValueError(f"currency must be a 3-letter code, got {currency[:10]!r}")
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


def _mark_unknown_currencies(db: Session, rows: list[ImportRow]) -> None:
    """
    An unknown code would fail the currency FK at confirm time (a 500 that
    throws the batch away) and send a made-up code to the FX provider.
    """
    known = {code for (code,) in db.query(Currency.code).all()}
    for row in rows:
        if row.is_parsable and row.currency not in known:
            row.is_parsable = False
            row.error = f"Unknown currency {row.currency!r}"


def _mark_after_closure(
    rows: Sequence["ImportRow | AssetImportRow"], closed_at: date_ | None
) -> None:
    """
    A closed account refuses movements dated after its closing day, so such
    rows are unparsable here rather than a 409 at confirm time that would
    throw away the rest of the batch.
    """
    if closed_at is None:
        return
    for row in rows:
        if row.is_parsable and row.date > closed_at:
            row.is_parsable = False
            row.error = f"Dated after the account was closed ({closed_at.isoformat()})"


def parse_csv(
    db: Session, account_id: UUID, file_content: bytes, *, closed_at: date_ | None = None
) -> ImportPreviewData:
    rows = [
        _parse_row(i, account_id, raw) for i, raw in enumerate(_read_rows(file_content), start=1)
    ]
    _mark_unknown_currencies(db, rows)
    _mark_after_closure(rows, closed_at)
    _mark_duplicates(db, rows)

    _evict_expired()
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
        if not re.fullmatch(SYMBOL_PATTERN, symbol):
            raise ValueError(f"invalid symbol: {symbol[:25]!r}")

        asset_type = raw["asset_type"].strip().lower()
        if asset_type not in ("stock", "etf", "crypto"):
            raise ValueError(f"asset_type must be stock/etf/crypto, got {asset_type!r}")

        transaction_type = raw["type"].strip().lower()
        if transaction_type not in ("buy", "sell"):
            raise ValueError(f"type must be buy/sell, got {transaction_type!r}")

        quantity = _decimal(raw["quantity"])
        price = _decimal(raw["price"])
        if quantity <= 0 or price <= 0:
            raise ValueError("quantity and price must both be positive")

        fee = _decimal(raw.get("fee", "").strip() or "0")
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


def parse_asset_csv(
    db: Session, account_id: UUID, file_content: bytes, *, closed_at: date_ | None = None
) -> AssetImportPreviewData:
    rows = [
        _parse_asset_row(i, account_id, raw)
        for i, raw in enumerate(_read_rows(file_content), start=1)
    ]
    _mark_after_closure(rows, closed_at)
    _mark_asset_duplicates(db, rows)

    _evict_expired()
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
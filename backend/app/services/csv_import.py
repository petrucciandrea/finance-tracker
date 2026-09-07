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
from datetime import date as date_, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import Transaction

_PREVIEW_TTL = timedelta(minutes=15)
_preview_store: dict[UUID, "ImportPreviewData"] = {}


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
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def _is_expired(preview: ImportPreviewData) -> bool:
    return datetime.now(timezone.utc) - preview.created_at > _PREVIEW_TTL


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
    if _is_expired(preview):
        _preview_store.pop(import_id, None)
        return None
    return preview


def discard_preview(import_id: UUID) -> None:
    _preview_store.pop(import_id, None)
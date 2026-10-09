"""
Retention: remove what no longer has a reason to exist.

Run periodically by `python -m app.purge` (`make purge`); scheduling is up to the
deployment (cron, a scheduled job on the host). Everything here is permanent.

What goes, and what deliberately stays:
- refresh tokens that expired or were revoked a while ago: nothing references them.
- soft-deleted rows older than the retention window, *unless something still
  points at them*. A deleted account or category that live transactions refer to
  stays: those transactions keep their FK on purpose so history renders "deleted"
  instead of breaking (see CLAUDE.md). Purging it would either fail on the FK or
  erase part of the user's own history.
- accounts that never completed signup: rejected ones, and ones that never
  confirmed their email (they can't log in, so they hold no data).
"""

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import and_, delete, exists, or_, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Base, User
from app.models.refresh_token import RefreshToken
from app.services.user_data import OWNED_TABLES, erase_user


def _run_delete(db: Session, statement: Any) -> int:
    # Session.execute is typed as a plain Result; a DELETE actually returns a
    # CursorResult, which is where rowcount lives.
    return cast(CursorResult, db.execute(statement)).rowcount or 0


def _purge_refresh_tokens(db: Session, cutoff: datetime) -> int:
    return _run_delete(
        db,
        delete(RefreshToken).where(
            or_(RefreshToken.expires_at < cutoff, RefreshToken.revoked_at < cutoff)
        ),
    )


def _unreferenced_old_rows(table: Any, cutoff: datetime) -> Any:
    """DELETE for the soft-deleted rows of `table` that nothing else points at."""
    blockers = []
    for other in Base.metadata.tables.values():
        for fk in other.foreign_keys:
            if fk.column.table is not table:
                continue
            if other is table:
                # A row pointing at another row of the same table (the two legs
                # of a transfer, a subcategory) only blocks while it survives:
                # when both are old they go together in one statement.
                child = table.alias()
                survives = or_(child.c.deleted_at.is_(None), child.c.deleted_at >= cutoff)
                points_at_row = child.c[fk.parent.name] == table.c[fk.column.name]
                blockers.append(exists().where(and_(points_at_row, survives)))
            else:
                # Any other reference blocks. Tables are visited children-first,
                # so the references from old soft-deleted rows are already gone.
                blockers.append(exists().where(other.c[fk.parent.name] == table.c[fk.column.name]))
    condition = table.c.deleted_at < cutoff
    if blockers:
        condition = and_(condition, ~or_(*blockers))
    return delete(table).where(condition)


def _purge_soft_deleted(db: Session, cutoff: datetime) -> dict[str, int]:
    purged: dict[str, int] = {}
    for name, _ in OWNED_TABLES:  # children first: that order is what makes this safe
        table = Base.metadata.tables[name]
        if "deleted_at" not in table.c:
            continue
        count = _run_delete(db, _unreferenced_old_rows(table, cutoff))
        if count:
            purged[name] = count
    return purged


def _purge_unfinished_accounts(db: Session, now: datetime) -> dict[str, int]:
    rejected_before = now - timedelta(days=settings.rejected_account_retention_days)
    unverified_before = now - timedelta(days=settings.unverified_account_retention_days)
    rejected = select(User.id).where(
        User.approval_status == "rejected", User.created_at < rejected_before
    )
    # Approved but never confirmed: only meaningful when verification is on.
    unverified = select(User.id).where(
        User.approval_status == "approved",
        User.email_verified_at.is_(None),
        User.created_at < unverified_before,
    )
    counts = {}
    for label, query in (("rejected_users", rejected), ("unverified_users", unverified)):
        ids = list(db.scalars(query))
        for user_id in ids:
            erase_user(db, user_id)
        counts[label] = len(ids)
    return counts


def purge(db: Session, now: datetime | None = None) -> dict[str, int]:
    """Apply every retention rule. Does not commit; `now` is injectable for tests."""
    now = now or datetime.now(UTC)
    report = {
        "refresh_tokens": _purge_refresh_tokens(
            db, now - timedelta(days=settings.refresh_token_retention_days)
        ),
    }
    for table, count in _purge_soft_deleted(
        db, now - timedelta(days=settings.soft_delete_retention_days)
    ).items():
        report[table] = count
    report.update(_purge_unfinished_accounts(db, now))
    return report

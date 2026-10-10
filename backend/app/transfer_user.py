"""
Copy ONE user and everything they own from one database into another:
`TARGET_DATABASE_URL=… python -m app.transfer_user you@example.com [--dry-run]`.

Made for moving a personal account from the local database to production without
dragging the rest of it along (test users, other people's data). The source is the
app's own DATABASE_URL; the target comes from TARGET_DATABASE_URL, so the production
password never appears on a command line.

It reuses the table registry behind account deletion/export (`OWNED_TABLES`), so a new
table can't be forgotten. Rules:
- the target must already be migrated to the same Alembic revision (`alembic upgrade head`);
- ids, amounts, timestamps and the password hash are copied as they are;
- sessions (refresh tokens) are not copied: log in again;
- soft-deleted rows travel too, because live rows may still point at them;
- the whole copy is one transaction on the target: everything or nothing;
- a user that already exists on the target is refused, never overwritten.
"""

import argparse
import os
import sys
from typing import Any

from sqlalchemy import create_engine, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection

from app.core.config import settings, to_psycopg_url
from app.models import Base
from app.services.user_data import OWNED_TABLES

# Sessions don't travel; the person simply logs in again on the new database.
SKIP_TABLES = {"refresh_tokens"}


class TransferError(Exception):
    """Something makes the copy unsafe; nothing has been written."""


def _revision(conn: Connection) -> str | None:
    return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()


def _self_references(table: Any) -> list[str]:
    # Columns pointing at the same table (a subcategory's parent, a transfer's other leg).
    return [fk.parent.name for fk in table.foreign_keys if fk.column.table is table]


def copy_user(
    source: Connection, target: Connection, email: str, *, check_version: bool = True
) -> dict[str, tuple[int, int]]:
    """
    Copy the user into `target` and return {table: (rows in source, rows now in target)}.
    Does not commit: the caller decides (dry run = roll back).
    """
    users = Base.metadata.tables["users"]
    user = source.execute(select(users).where(users.c.email == email)).mappings().first()
    if user is None:
        raise TransferError(f"No user {email!r} in the source database.")
    uid = user["id"]

    if check_version and _revision(source) != _revision(target):
        raise TransferError(
            "The two databases are at different Alembic revisions "
            f"({_revision(source)} vs {_revision(target)}): migrate the target first."
        )
    taken = target.execute(
        select(users.c.id).where((users.c.id == uid) | (users.c.email == email))
    ).first()
    if taken is not None:
        raise TransferError("That user already exists in the target database; not overwriting it.")

    target.execute(users.insert(), [dict(user)])

    # Shared catalogue rows the user's data points at (the securities they hold).
    assets = Base.metadata.tables["assets"]
    asset_ids: set[Any] = set()
    for name, where in OWNED_TABLES:
        table = Base.metadata.tables[name]
        if "asset_id" in table.c:
            query = select(table.c.asset_id).where(text(where)).where(table.c.asset_id.isnot(None))
            asset_ids.update(r[0] for r in source.execute(query, {"uid": uid}))
    if asset_ids:
        found = source.execute(select(assets).where(assets.c.id.in_(asset_ids))).mappings()
        target.execute(pg_insert(assets).on_conflict_do_nothing(), [dict(r) for r in found])

    report: dict[str, tuple[int, int]] = {"users": (1, 1)}
    for name, where in reversed(OWNED_TABLES):  # parents first, so every FK target exists
        if name in SKIP_TABLES:
            continue
        table = Base.metadata.tables[name]
        rows = [
            dict(r)
            for r in source.execute(select(table).where(text(where)), {"uid": uid}).mappings()
        ]
        if rows:
            # Rows of one table can point at each other in any order (even in a cycle,
            # like the two legs of a transfer), so they go in with those links empty and
            # get them back once every row is there.
            links = _self_references(table)
            target.execute(table.insert(), [{**r, **{c: None for c in links}} for r in rows])
            for row in rows:
                restored = {c: row[c] for c in links if row[c] is not None}
                if restored:
                    target.execute(update(table).where(table.c.id == row["id"]).values(**restored))
        copied = target.execute(
            select(func.count()).select_from(table).where(text(where)), {"uid": uid}
        ).scalar_one()
        report[name] = (len(rows), copied)
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Copy one user's data into another database.")
    parser.add_argument("email")
    parser.add_argument("--dry-run", action="store_true", help="do everything, then roll back")
    args = parser.parse_args(argv)

    target_url = os.environ.get("TARGET_DATABASE_URL")
    if not target_url:
        sys.exit(
            "Set TARGET_DATABASE_URL to the destination database (never pass it as an argument)."
        )
    target_url = str(to_psycopg_url(target_url))
    if target_url == str(settings.database_url):
        sys.exit("The target is the same database as the source.")

    source_engine = create_engine(str(settings.database_url))
    target_engine = create_engine(target_url)
    email = args.email.strip().lower()
    with source_engine.connect() as source, target_engine.connect() as target:
        transaction = target.begin()
        try:
            report = copy_user(source, target, email)
        except TransferError as error:
            transaction.rollback()
            sys.exit(str(error))
        except Exception:
            transaction.rollback()
            raise
        mismatched = [name for name, (src, dst) in report.items() if src != dst]
        if mismatched:
            transaction.rollback()
            sys.exit(f"Row counts differ for {mismatched}: rolled back, nothing was copied.")
        if args.dry_run:
            transaction.rollback()
        else:
            transaction.commit()

    print(("Dry run (rolled back)" if args.dry_run else "Copied") + f" {email}:")
    for name, (src, dst) in report.items():
        if src or dst:
            print(f"  {name}: {src} -> {dst}")


if __name__ == "__main__":
    main()

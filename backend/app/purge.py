"""
Entry point for the retention job: `python -m app.purge [--dry-run]`.

--dry-run runs every rule, prints what it would remove, then rolls back.
"""

import argparse

from app.db.session import SessionLocal
from app.services import retention


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Apply the data retention rules.")
    parser.add_argument("--dry-run", action="store_true", help="report only, change nothing")
    args = parser.parse_args(argv)

    with SessionLocal() as db:
        report = retention.purge(db)
        if args.dry_run:
            db.rollback()
        else:
            db.commit()

    verb = "would remove" if args.dry_run else "removed"
    total = sum(report.values())
    print(f"{verb} {total} row(s)")
    for name, count in sorted(report.items()):
        if count:
            print(f"  {name}: {count}")


if __name__ == "__main__":
    main()

"""
Create an account without going through registration:
`python -m app.create_user you@example.com [--currency EUR]`.

With registration closed this is how a user comes to exist. The password is asked
for interactively (never as an argument, which would land in shell history and the
process list). The account is created approved and with its email already marked
as confirmed: the person running this is vouching for it.
"""

import argparse
import getpass
import sys
from datetime import UTC, datetime

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import Currency, User


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Create a user directly in the database.")
    parser.add_argument("email")
    parser.add_argument("--currency", default="EUR", help="base currency (default: EUR)")
    args = parser.parse_args(argv)

    email = args.email.strip().lower()
    currency = args.currency.strip().upper()

    password = getpass.getpass("Password: ")
    if not 8 <= len(password) <= 256:
        sys.exit("The password must be between 8 and 256 characters.")
    if password != getpass.getpass("Repeat password: "):
        sys.exit("The two passwords do not match.")

    with SessionLocal() as db:
        if db.get(Currency, currency) is None:
            sys.exit(f"Unknown currency {currency!r}.")
        if db.query(User).filter(User.email == email).first() is not None:
            sys.exit(f"A user with the email {email} already exists.")
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                base_currency=currency,
                approval_status="approved",
                email_verified_at=datetime.now(UTC),
            )
        )
        db.commit()
    print(f"Created {email} ({currency}).")


if __name__ == "__main__":
    main()

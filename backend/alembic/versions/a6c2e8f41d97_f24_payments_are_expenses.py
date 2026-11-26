"""F24 payments are expenses (cash basis), filed under "Tasse"

Revision ID: a6c2e8f41d97
Revises: d3f9b6a24c81
Create Date: 2026-11-26 19:00:00.000000

Data only. Every live movement of a paid F24 was a one-sided `transfer` (the
tax counted as a cost when the invoice was collected); from now on it is an
`expense`, and the planning engine reads income gross. Left as transfers, the
months before this release would count the taxes nowhere at all.

Each user's movements go into an existing leaf expense category named
"Tasse", or one created here as `primary` (same as
`ownership.get_or_create_taxes_category`). Any transfer category they had is
replaced: it can't sit on an expense.

Compatible with the code still running during a deploy: it only ever reads
these movements through the payment row, whatever their type.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a6c2e8f41d97"
down_revision: str | Sequence[str] | None = "d3f9b6a24c81"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_F24_MOVEMENTS = """
    SELECT t.id
    FROM transactions t
    JOIN tax_payments p ON p.transaction_id = t.id
    WHERE p.deleted_at IS NULL
      AND p.status = 'paid'
      AND p.user_id = :user_id
      AND t.deleted_at IS NULL
"""


def upgrade() -> None:
    conn = op.get_bind()
    users = conn.execute(
        sa.text(
            """
            SELECT DISTINCT p.user_id
            FROM tax_payments p
            JOIN transactions t ON t.id = p.transaction_id
            WHERE p.deleted_at IS NULL AND p.status = 'paid'
              AND t.deleted_at IS NULL AND t.type = 'transfer'
            """
        )
    ).scalars()
    for user_id in list(users):
        category_id = conn.execute(
            sa.text(
                """
                SELECT c.id FROM categories c
                WHERE c.user_id = :user_id AND c.name = 'Tasse' AND c.type = 'expense'
                  AND c.deleted_at IS NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM categories k
                      WHERE k.parent_id = c.id AND k.deleted_at IS NULL
                  )
                ORDER BY c.id
                LIMIT 1
                """
            ),
            {"user_id": user_id},
        ).scalar()
        if category_id is None:
            category_id = conn.execute(
                sa.text(
                    """
                    INSERT INTO categories
                        (id, user_id, name, type, parent_id, necessity_level,
                         excluded_from_income_base)
                    VALUES
                        (gen_random_uuid(), :user_id, 'Tasse', 'expense', NULL, 'primary', false)
                    RETURNING id
                    """
                ),
                {"user_id": user_id},
            ).scalar()
        conn.execute(
            sa.text(
                f"""
                UPDATE transactions
                SET type = 'expense', category_id = :category_id
                WHERE type = 'transfer' AND id IN ({_F24_MOVEMENTS})
                """
            ),
            {"user_id": user_id, "category_id": category_id},
        )


def downgrade() -> None:
    # Back to the accrual model's shape. The transfer category an F24 might
    # have had is not kept, and "Tasse" stays: it may hold other spend by now.
    op.execute(
        """
        UPDATE transactions t
        SET type = 'transfer', category_id = NULL, necessity_level_override = NULL
        FROM tax_payments p
        WHERE p.transaction_id = t.id
          AND p.deleted_at IS NULL AND p.status = 'paid'
          AND t.deleted_at IS NULL AND t.type = 'expense'
        """
    )

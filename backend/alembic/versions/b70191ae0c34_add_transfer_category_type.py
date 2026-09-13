"""add transfer category type

Revision ID: b70191ae0c34
Revises: 72d8347009eb
Create Date: 2026-09-13 17:10:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b70191ae0c34'
down_revision: Union[str, Sequence[str], None] = '72d8347009eb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint('ck_categories_type', 'categories', type_='check')
    op.create_check_constraint(
        'ck_categories_type', 'categories', "type in ('expense','income','transfer')"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('ck_categories_type', 'categories', type_='check')
    op.create_check_constraint('ck_categories_type', 'categories', "type in ('expense','income')")

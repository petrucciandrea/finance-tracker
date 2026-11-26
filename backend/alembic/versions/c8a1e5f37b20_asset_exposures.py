"""per-user exposures of a product: asset class, region, sector, currency

Revision ID: c8a1e5f37b20
Revises: b2f7d4e81c63
Create Date: 2026-11-26 15:00:00.000000

New tables only. The reference weights for common products ship as a file
with the code (`app/data/asset_exposures.json`), not as rows: they reach
production with the deploy and need no data migration.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8a1e5f37b20"
down_revision: str | Sequence[str] | None = "b2f7d4e81c63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "asset_exposures",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "asset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("assets.id"), nullable=False
        ),
        sa.Column("dimension", sa.String(12), nullable=False),
        sa.Column("bucket", sa.String(30), nullable=False),
        sa.Column("weight", sa.Numeric(7, 4), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint(
            "user_id", "asset_id", "dimension", "bucket", name="uq_asset_exposures_bucket"
        ),
        sa.CheckConstraint(
            "dimension in ('asset_class','region','sector','currency')",
            name="ck_asset_exposures_dimension",
        ),
        sa.CheckConstraint("weight > 0 AND weight <= 100", name="ck_asset_exposures_weight"),
    )
    op.create_index("ix_asset_exposures_user_id", "asset_exposures", ["user_id"])
    op.create_table(
        "asset_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "asset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("assets.id"), nullable=False
        ),
        sa.Column("as_of", sa.Date(), nullable=True),
        sa.Column("notes", sa.String(500), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("user_id", "asset_id", name="uq_asset_profiles_asset"),
    )
    op.create_index("ix_asset_profiles_user_id", "asset_profiles", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_asset_profiles_user_id", table_name="asset_profiles")
    op.drop_table("asset_profiles")
    op.drop_index("ix_asset_exposures_user_id", table_name="asset_exposures")
    op.drop_table("asset_exposures")

"""Add pnl snapshot table

Revision ID: 20250115_0004
Revises: 20250115_0003
Create Date: 2025-01-15 00:04:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20250115_0004"
down_revision = "20250115_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pnl_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("product_id", sa.String(length=20), nullable=False),
        sa.Column("summary_json", sa.JSON(), nullable=False),
    )
    op.create_index("ix_pnl_snapshots_ts", "pnl_snapshots", ["ts"])
    op.create_index("ix_pnl_snapshots_product_id", "pnl_snapshots", ["product_id"])


def downgrade() -> None:
    op.drop_index("ix_pnl_snapshots_product_id", table_name="pnl_snapshots")
    op.drop_index("ix_pnl_snapshots_ts", table_name="pnl_snapshots")
    op.drop_table("pnl_snapshots")

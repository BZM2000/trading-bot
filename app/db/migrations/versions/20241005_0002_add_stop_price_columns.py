"""Add stop price columns to order tables

Revision ID: 20241005_0002
Revises: 20240801_0001
Create Date: 2024-10-05 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20241005_0002"
down_revision = "20240801_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "executed_orders",
        sa.Column("stop_price", sa.Numeric(precision=18, scale=8), nullable=True),
    )
    op.add_column(
        "open_orders",
        sa.Column("stop_price", sa.Numeric(precision=18, scale=8), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("open_orders", "stop_price")
    op.drop_column("executed_orders", "stop_price")

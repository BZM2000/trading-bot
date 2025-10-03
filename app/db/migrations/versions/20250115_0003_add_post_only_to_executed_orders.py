"""Add post_only flag to executed orders

Revision ID: 20250115_0003
Revises: 20241005_0002
Create Date: 2025-01-15 00:03:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20250115_0003"
down_revision = "20241005_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("executed_orders", sa.Column("post_only", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("executed_orders", "post_only")


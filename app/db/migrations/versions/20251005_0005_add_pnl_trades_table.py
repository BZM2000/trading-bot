"""Add pnl trades cache table

Revision ID: 20251005_0005
Revises: 20250115_0004
Create Date: 2025-10-05 13:50:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20251005_0005"
down_revision = "20250115_0004"
branch_labels = None
depends_on = None


ENUM_NAME = "pnl_trade_side"


def _ensure_postgres_enum(bind: sa.engine.Connection) -> None:
    existing = bind.execute(
        sa.text("SELECT 1 FROM pg_type WHERE typname = :name"),
        {"name": ENUM_NAME},
    ).scalar()
    if not existing:
        postgresql.ENUM("BUY", "SELL", name=ENUM_NAME).create(bind, checkfirst=False)


def _column_type(bind: sa.engine.Connection) -> sa.types.TypeEngine:
    if bind.dialect.name == "postgresql":
        return postgresql.ENUM("BUY", "SELL", name=ENUM_NAME, create_type=False)
    return sa.Enum("BUY", "SELL", name=ENUM_NAME)


def upgrade() -> None:
    bind = op.get_bind()

    if bind.dialect.name == "postgresql":
        _ensure_postgres_enum(bind)

    enum_type = _column_type(bind)

    op.create_table(
        "pnl_trades",
        sa.Column("fill_id", sa.String(length=120), primary_key=True),
        sa.Column("order_id", sa.String(length=100), nullable=True),
        sa.Column("product_id", sa.String(length=20), nullable=False),
        sa.Column("trade_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("side", enum_type, nullable=False),
        sa.Column("price", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("size", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("post_only", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("raw_json", sa.JSON(), nullable=True),
        sa.Column("inserted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_pnl_trades_product_id", "pnl_trades", ["product_id"])
    op.create_index("ix_pnl_trades_trade_time", "pnl_trades", ["trade_time"])
    op.create_index("ix_pnl_trades_order_id", "pnl_trades", ["order_id"])


def downgrade() -> None:
    op.drop_index("ix_pnl_trades_order_id", table_name="pnl_trades")
    op.drop_index("ix_pnl_trades_trade_time", table_name="pnl_trades")
    op.drop_index("ix_pnl_trades_product_id", table_name="pnl_trades")
    op.drop_table("pnl_trades")
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        existing = bind.execute(
            sa.text("SELECT 1 FROM pg_type WHERE typname = :name"),
            {"name": ENUM_NAME},
        ).scalar()
        if existing:
            postgresql.ENUM("BUY", "SELL", name=ENUM_NAME).drop(bind, checkfirst=False)

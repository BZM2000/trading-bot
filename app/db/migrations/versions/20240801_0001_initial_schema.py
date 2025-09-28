"""Initial schema

Revision ID: 20240801_0001
Revises: 
Create Date: 2024-08-01 00:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20240801_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_kind_enum = postgresql.ENUM("daily", "2h", "5m", "manual", name="run_kind")
    run_status_enum = postgresql.ENUM("running", "success", "failed", name="run_status")
    order_side_enum = postgresql.ENUM("BUY", "SELL", name="order_side")
    order_status_enum = postgresql.ENUM(
        "NEW", "OPEN", "FILLED", "CANCELLED", "EXPIRED", name="order_status"
    )
    open_order_side_enum = postgresql.ENUM("BUY", "SELL", name="open_order_side")
    open_order_status_enum = postgresql.ENUM(
        "NEW", "OPEN", "FILLED", "CANCELLED", "EXPIRED", name="open_order_status"
    )

    bind = op.get_bind()
    for enum_type in (
        run_kind_enum,
        run_status_enum,
        order_side_enum,
        order_status_enum,
        open_order_side_enum,
        open_order_status_enum,
    ):
        enum_type.create(bind, checkfirst=True)
        enum_type.create_type = False

    op.create_table(
        "run_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kind", run_kind_enum, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", run_status_enum, nullable=False),
        sa.Column("usage_json", sa.JSON(), nullable=True),
        sa.Column("error_text", sa.Text(), nullable=True),
    )

    op.create_index("ix_run_logs_kind", "run_logs", ["kind"])

    op.create_table(
        "prompt_history_daily",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column("response_text", sa.Text(), nullable=False),
        sa.Column("compact_summary_500w", sa.Text(), nullable=True),
        sa.Column("sources_json", sa.JSON(), nullable=True),
    )
    op.create_index("ix_prompt_history_daily_ts", "prompt_history_daily", ["ts"])

    op.create_table(
        "prompt_history_2h",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column("response_text", sa.Text(), nullable=False),
        sa.Column("compact_summary_500w", sa.Text(), nullable=True),
        sa.Column("sources_json", sa.JSON(), nullable=True),
    )
    op.create_index("ix_prompt_history_2h_ts", "prompt_history_2h", ["ts"])

    op.create_table(
        "executed_orders",
        sa.Column("order_id", sa.String(length=100), primary_key=True),
        sa.Column("ts_submitted", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ts_filled", sa.DateTime(timezone=True), nullable=True),
        sa.Column("side", order_side_enum, nullable=False),
        sa.Column("limit_price", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("base_size", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("status", order_status_enum, nullable=False),
        sa.Column("filled_size", sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column("client_order_id", sa.String(length=120), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("product_id", sa.String(length=20), nullable=False),
    )
    op.create_index("ix_executed_orders_ts_submitted", "executed_orders", ["ts_submitted"])
    op.create_index("ix_executed_orders_end_time", "executed_orders", ["end_time"])
    op.create_index("ix_executed_orders_product_id", "executed_orders", ["product_id"])
    op.create_index("ix_executed_orders_client_order_id", "executed_orders", ["client_order_id"])

    op.create_table(
        "open_orders",
        sa.Column("order_id", sa.String(length=100), primary_key=True),
        sa.Column("side", open_order_side_enum, nullable=False),
        sa.Column("limit_price", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("base_size", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("status", open_order_status_enum, nullable=False),
        sa.Column("client_order_id", sa.String(length=120), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("product_id", sa.String(length=20), nullable=False),
    )
    op.create_index("ix_open_orders_end_time", "open_orders", ["end_time"])
    op.create_index("ix_open_orders_product_id", "open_orders", ["product_id"])
    op.create_index("ix_open_orders_client_order_id", "open_orders", ["client_order_id"])

    op.create_table(
        "portfolio_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("balances_json", sa.JSON(), nullable=False),
    )
    op.create_index("ix_portfolio_snapshots_ts", "portfolio_snapshots", ["ts"])

    op.create_table(
        "price_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("product_id", sa.String(length=20), nullable=False),
        sa.Column("best_bid", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("best_ask", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("mid", sa.Numeric(precision=18, scale=8), nullable=False),
    )
    op.create_index("ix_price_snapshots_ts", "price_snapshots", ["ts"])
    op.create_index("ix_price_snapshots_product_id", "price_snapshots", ["product_id"])

    op.create_table(
        "daily_plans",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("machine_json", sa.JSON(), nullable=True),
    )
    op.create_index("ix_daily_plans_ts", "daily_plans", ["ts"])

    op.create_table(
        "two_hour_plans",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("t0_mid", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("machine_json", sa.JSON(), nullable=True),
    )
    op.create_index("ix_two_hour_plans_ts", "two_hour_plans", ["ts"])


def downgrade() -> None:
    op.drop_index("ix_two_hour_plans_ts", table_name="two_hour_plans")
    op.drop_table("two_hour_plans")

    op.drop_index("ix_daily_plans_ts", table_name="daily_plans")
    op.drop_table("daily_plans")

    op.drop_index("ix_price_snapshots_product_id", table_name="price_snapshots")
    op.drop_index("ix_price_snapshots_ts", table_name="price_snapshots")
    op.drop_table("price_snapshots")

    op.drop_index("ix_portfolio_snapshots_ts", table_name="portfolio_snapshots")
    op.drop_table("portfolio_snapshots")

    op.drop_index("ix_open_orders_client_order_id", table_name="open_orders")
    op.drop_index("ix_open_orders_product_id", table_name="open_orders")
    op.drop_index("ix_open_orders_end_time", table_name="open_orders")
    op.drop_table("open_orders")

    op.drop_index("ix_executed_orders_client_order_id", table_name="executed_orders")
    op.drop_index("ix_executed_orders_product_id", table_name="executed_orders")
    op.drop_index("ix_executed_orders_end_time", table_name="executed_orders")
    op.drop_index("ix_executed_orders_ts_submitted", table_name="executed_orders")
    op.drop_table("executed_orders")

    op.drop_index("ix_prompt_history_2h_ts", table_name="prompt_history_2h")
    op.drop_table("prompt_history_2h")

    op.drop_index("ix_prompt_history_daily_ts", table_name="prompt_history_daily")
    op.drop_table("prompt_history_daily")

    op.drop_index("ix_run_logs_kind", table_name="run_logs")
    op.drop_table("run_logs")

    bind = op.get_bind()
    postgresql.ENUM(
        "NEW", "OPEN", "FILLED", "CANCELLED", "EXPIRED", name="open_order_status"
    ).drop(
        bind, checkfirst=True
    )
    postgresql.ENUM("BUY", "SELL", name="open_order_side").drop(
        bind, checkfirst=True
    )
    postgresql.ENUM(
        "NEW", "OPEN", "FILLED", "CANCELLED", "EXPIRED", name="order_status"
    ).drop(
        bind, checkfirst=True
    )
    postgresql.ENUM("BUY", "SELL", name="order_side").drop(bind, checkfirst=True)
    postgresql.ENUM("running", "success", "failed", name="run_status").drop(bind, checkfirst=True)
    postgresql.ENUM("daily", "2h", "5m", "manual", name="run_kind").drop(bind, checkfirst=True)

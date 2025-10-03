from __future__ import annotations

import enum
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, Enum, Integer, JSON, Numeric, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


NUMERIC_18_8 = Numeric(precision=18, scale=8, asdecimal=True)
NUMERIC_18_4 = Numeric(precision=18, scale=4, asdecimal=True)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class RunKind(str, enum.Enum):
    DAILY = "daily"
    TWO_HOURLY = "2h"
    FIVE_MINUTE = "5m"
    MANUAL = "manual"


class RunStatus(str, enum.Enum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


def _enum_values(enum_cls: type[enum.Enum]) -> list[str]:
    """Return the JSON-serialisable values for a SQLAlchemy Enum."""

    return [member.value for member in enum_cls]


class OrderSide(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, enum.Enum):
    NEW = "NEW"
    OPEN = "OPEN"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class RunLog(Base):
    __tablename__ = "run_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[RunKind] = mapped_column(
        Enum(RunKind, name="run_kind", values_callable=_enum_values, validate_strings=True),
        nullable=False,
        index=True,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[RunStatus] = mapped_column(
        Enum(RunStatus, name="run_status", values_callable=_enum_values, validate_strings=True),
        default=RunStatus.RUNNING,
        nullable=False,
    )
    usage_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    error_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class PromptHistoryDaily(Base):
    __tablename__ = "prompt_history_daily"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    response_text: Mapped[str] = mapped_column(Text, nullable=False)
    compact_summary_500w: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sources_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)


class PromptHistory2H(Base):
    __tablename__ = "prompt_history_2h"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    response_text: Mapped[str] = mapped_column(Text, nullable=False)
    compact_summary_500w: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sources_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)


class ExecutedOrder(Base):
    __tablename__ = "executed_orders"

    order_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    ts_submitted: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ts_filled: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    side: Mapped[OrderSide] = mapped_column(Enum(OrderSide, name="order_side"), nullable=False)
    limit_price: Mapped[Decimal] = mapped_column(NUMERIC_18_8, nullable=False)
    base_size: Mapped[Decimal] = mapped_column(NUMERIC_18_8, nullable=False)
    stop_price: Mapped[Optional[Decimal]] = mapped_column(NUMERIC_18_8, nullable=True)
    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus, name="order_status"), nullable=False)
    filled_size: Mapped[Optional[Decimal]] = mapped_column(NUMERIC_18_8, nullable=True)
    client_order_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    product_id: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    post_only: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)


class OpenOrder(Base):
    __tablename__ = "open_orders"

    order_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    side: Mapped[OrderSide] = mapped_column(Enum(OrderSide, name="open_order_side"), nullable=False)
    limit_price: Mapped[Decimal] = mapped_column(NUMERIC_18_8, nullable=False)
    base_size: Mapped[Decimal] = mapped_column(NUMERIC_18_8, nullable=False)
    stop_price: Mapped[Optional[Decimal]] = mapped_column(NUMERIC_18_8, nullable=True)
    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus, name="open_order_status"), nullable=False)
    client_order_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    product_id: Mapped[str] = mapped_column(String(20), nullable=False, index=True)


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    balances_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class PriceSnapshot(Base):
    __tablename__ = "price_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    product_id: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    best_bid: Mapped[Decimal] = mapped_column(NUMERIC_18_8, nullable=False)
    best_ask: Mapped[Decimal] = mapped_column(NUMERIC_18_8, nullable=False)
    mid: Mapped[Decimal] = mapped_column(NUMERIC_18_8, nullable=False)


class PnLSnapshot(Base):
    __tablename__ = "pnl_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    product_id: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class DailyPlan(Base):
    __tablename__ = "daily_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    machine_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)


class TwoHourPlan(Base):
    __tablename__ = "two_hour_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(nullable=False, index=True)
    t0_mid: Mapped[Decimal] = mapped_column(NUMERIC_18_8, nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    machine_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)

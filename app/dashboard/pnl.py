from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Iterable, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models


MAKER_FEE_RATE = Decimal("0.0025")
TAKER_FEE_RATE = Decimal("0.0015")
CUTOFF_TS = datetime(2025, 1, 1, tzinfo=timezone.utc)


@dataclass(slots=True)
class TradeSnapshot:
    timestamp: datetime
    side: models.OrderSide
    price: Decimal
    size: Decimal
    post_only: bool


@dataclass(slots=True)
class IntervalMetrics:
    key: str
    label: str
    profit_before_fees: Decimal
    maker_volume: Decimal
    taker_volume: Decimal
    fee_total: Decimal
    profit_after_fees: Decimal


@dataclass(slots=True)
class PNLSummary:
    intervals: list[IntervalMetrics]
    total_profit_before_fees: Decimal
    total_profit_after_fees: Decimal


def calculate_pnl_summary(
    session: Session,
    *,
    product_id: str,
    now: Optional[datetime] = None,
) -> PNLSummary:
    """Aggregate profit metrics for dashboard display."""

    aware_now = _ensure_aware(now or datetime.now(timezone.utc))
    trades = _load_trades(session, product_id=product_id)

    intervals: list[IntervalMetrics] = []
    for key, label, delta in _timeframes():
        start = _effective_start(aware_now, delta)
        metrics = _summarise_interval(trades, start=start)
        intervals.append(
            IntervalMetrics(
                key=key,
                label=label,
                profit_before_fees=metrics.profit_before_fees,
                maker_volume=metrics.maker_volume,
                taker_volume=metrics.taker_volume,
                fee_total=metrics.fee_total,
                profit_after_fees=metrics.profit_after_fees,
            )
        )

    total_before_fees = Decimal("0")
    total_after_fees = Decimal("0")
    for interval in intervals:
        if interval.key == "all":
            total_before_fees = interval.profit_before_fees
            total_after_fees = interval.profit_after_fees
            break

    return PNLSummary(
        intervals=intervals,
        total_profit_before_fees=total_before_fees,
        total_profit_after_fees=total_after_fees,
    )


def _timeframes() -> Iterable[tuple[str, str, Optional[timedelta]]]:
    return (
        ("24h", "Last 24 Hours", timedelta(hours=24)),
        ("7d", "Last 7 Days", timedelta(days=7)),
        ("30d", "Last 30 Days", timedelta(days=30)),
        ("365d", "Last 365 Days", timedelta(days=365)),
        ("all", "Since 2025", None),
    )


def _load_trades(session: Session, *, product_id: str) -> Sequence[TradeSnapshot]:
    statement = select(models.ExecutedOrder).where(models.ExecutedOrder.product_id == product_id)
    orders = session.scalars(statement).all()

    trades: list[TradeSnapshot] = []
    for order in orders:
        timestamp = _resolve_timestamp(order)
        if timestamp is None or timestamp < CUTOFF_TS:
            continue

        if order.side not in (models.OrderSide.BUY, models.OrderSide.SELL):
            continue

        price = order.limit_price
        filled_size = order.filled_size
        if price is None:
            continue
        if filled_size is None:
            if order.status is not models.OrderStatus.FILLED:
                continue
            filled_size = order.base_size
        if filled_size is None:
            continue

        try:
            price_decimal = Decimal(price)
            size_decimal = Decimal(filled_size)
        except Exception:  # pragma: no cover - defensive against malformed data
            continue

        if price_decimal <= 0 or size_decimal <= 0:
            continue

        post_only = bool(order.post_only)
        trades.append(
            TradeSnapshot(
                timestamp=timestamp,
                side=order.side,
                price=price_decimal,
                size=size_decimal,
                post_only=post_only,
            )
        )

    trades.sort(key=lambda trade: trade.timestamp)
    return trades


@dataclass(slots=True)
class _RawMetrics:
    profit_before_fees: Decimal
    maker_volume: Decimal
    taker_volume: Decimal
    fee_total: Decimal
    profit_after_fees: Decimal


def _summarise_interval(trades: Sequence[TradeSnapshot], *, start: datetime) -> _RawMetrics:
    profit_before = Decimal("0")
    maker_volume = Decimal("0")
    taker_volume = Decimal("0")

    for trade in trades:
        if trade.timestamp < start:
            continue

        notional = trade.price * trade.size
        if trade.side is models.OrderSide.SELL:
            profit_before += notional
        else:
            profit_before -= notional

        if trade.post_only:
            maker_volume += notional
        else:
            taker_volume += notional

    maker_fees = maker_volume * MAKER_FEE_RATE
    taker_fees = taker_volume * TAKER_FEE_RATE
    fee_total = maker_fees + taker_fees
    profit_after = profit_before - fee_total

    return _RawMetrics(
        profit_before_fees=profit_before,
        maker_volume=maker_volume,
        taker_volume=taker_volume,
        fee_total=fee_total,
        profit_after_fees=profit_after,
    )


def _resolve_timestamp(order: models.ExecutedOrder) -> Optional[datetime]:
    ts = order.ts_filled or order.ts_submitted
    if ts is None:
        return None
    return _ensure_aware(ts)


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _effective_start(now: datetime, delta: Optional[timedelta]) -> datetime:
    if delta is None:
        return CUTOFF_TS
    candidate = now - delta
    if candidate < CUTOFF_TS:
        return CUTOFF_TS
    return candidate

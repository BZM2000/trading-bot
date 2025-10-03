from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from string import hexdigits
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
    start_anchor: Optional[datetime] = None,
) -> PNLSummary:
    """Aggregate profit metrics for dashboard display."""

    aware_now = _ensure_aware(now or datetime.now(timezone.utc))
    trades = _load_trades(
        session,
        product_id=product_id,
        start_anchor=start_anchor,
    )
    entries = _build_entries(trades)

    intervals: list[IntervalMetrics] = []
    for key, label, delta in _timeframes():
        start = _effective_start(aware_now, delta)
        metrics = _summarise_interval(entries, start=start)
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


def _load_trades(
    session: Session,
    *,
    product_id: str,
    start_anchor: Optional[datetime],
) -> Sequence[TradeSnapshot]:
    statement = select(models.ExecutedOrder).where(models.ExecutedOrder.product_id == product_id)
    orders = session.scalars(statement).all()

    trades: list[TradeSnapshot] = []
    for order in orders:
        client_order_id = getattr(order, "client_order_id", "") or ""
        if not _is_bot_client_order_id(client_order_id):
            continue

        timestamp = _resolve_timestamp(order)
        if timestamp is None:
            continue
        if timestamp < CUTOFF_TS:
            continue
        if start_anchor and timestamp < start_anchor:
            continue

        if order.side not in (models.OrderSide.BUY, models.OrderSide.SELL):
            continue

        if order.status is not models.OrderStatus.FILLED:
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


def _build_entries(trades: Sequence[TradeSnapshot]) -> list["_PnLEntry"]:
    long_lots: deque[_Lot] = deque()
    short_lots: deque[_Lot] = deque()
    entries: list[_PnLEntry] = []

    zero = Decimal("0")

    for trade in trades:
        remaining = trade.size
        realized = Decimal("0")

        if trade.side is models.OrderSide.BUY:
            while remaining > zero and short_lots:
                lot = short_lots[0]
                matched = remaining if remaining <= lot.size else lot.size
                realized += (lot.price - trade.price) * matched
                lot.size -= matched
                remaining -= matched
                if lot.size <= zero:
                    short_lots.popleft()
            if remaining > zero:
                long_lots.append(_Lot(price=trade.price, size=remaining))
        else:
            while remaining > zero and long_lots:
                lot = long_lots[0]
                matched = remaining if remaining <= lot.size else lot.size
                realized += (trade.price - lot.price) * matched
                lot.size -= matched
                remaining -= matched
                if lot.size <= zero:
                    long_lots.popleft()
            if remaining > zero:
                short_lots.append(_Lot(price=trade.price, size=remaining))

        notional = trade.price * trade.size
        maker_volume = notional if trade.post_only else zero
        taker_volume = notional if not trade.post_only else zero
        fee_rate = MAKER_FEE_RATE if trade.post_only else TAKER_FEE_RATE
        fee = notional * fee_rate

        entries.append(
            _PnLEntry(
                timestamp=trade.timestamp,
                realized_profit=realized,
                maker_volume=maker_volume,
                taker_volume=taker_volume,
                fee=fee,
            )
        )

    return entries


def _is_bot_client_order_id(value: str) -> bool:
    if len(value) != 32:
        return False
    return all(char in hexdigits for char in value)


@dataclass(slots=True)
class _Lot:
    price: Decimal
    size: Decimal


@dataclass(slots=True)
class _PnLEntry:
    timestamp: datetime
    realized_profit: Decimal
    maker_volume: Decimal
    taker_volume: Decimal
    fee: Decimal


def _summarise_interval(entries: Sequence["_PnLEntry"], *, start: datetime) -> _RawMetrics:
    profit_before = Decimal("0")
    maker_volume = Decimal("0")
    taker_volume = Decimal("0")
    fee_total = Decimal("0")

    for entry in entries:
        if entry.timestamp < start:
            continue
        profit_before += entry.realized_profit
        maker_volume += entry.maker_volume
        taker_volume += entry.taker_volume
        fee_total += entry.fee

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

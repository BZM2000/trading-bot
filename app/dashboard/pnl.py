from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterable, Optional, Sequence

from app.coinbase.client import CoinbaseClient
from app.coinbase.exec import parse_decimal, parse_side, parse_datetime
from app.db import models


MAKER_FEE_RATE = Decimal("0.0025")
TAKER_FEE_RATE = Decimal("0.0015")
CUTOFF_TS = datetime(2025, 9, 1, tzinfo=timezone.utc)


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


async def calculate_pnl_summary(
    client: CoinbaseClient,
    *,
    product_id: str,
    now: Optional[datetime] = None,
) -> PNLSummary:
    """Hydrate PnL summary using Coinbase fills since 2025."""

    aware_now = _ensure_aware(now or datetime.now(timezone.utc))
    trades = await _load_trades_from_api(client, product_id=product_id, start_anchor=CUTOFF_TS)
    return _summarise_trades(trades, now=aware_now)


def summarise_trades(
    trades: Sequence[TradeSnapshot],
    *,
    now: Optional[datetime] = None,
) -> PNLSummary:
    """Summarise already-fetched trades into interval metrics."""

    aware_now = _ensure_aware(now or datetime.now(timezone.utc))
    return _summarise_trades(trades, now=aware_now)


def empty_summary(now: Optional[datetime] = None) -> PNLSummary:
    """Return a zeroed summary, useful when API access is unavailable."""

    return summarise_trades((), now=now)


def summary_to_json(summary: PNLSummary) -> dict[str, Any]:
    return {
        "intervals": [
            {
                "key": interval.key,
                "label": interval.label,
                "profit_before_fees": str(interval.profit_before_fees),
                "maker_volume": str(interval.maker_volume),
                "taker_volume": str(interval.taker_volume),
                "fee_total": str(interval.fee_total),
                "profit_after_fees": str(interval.profit_after_fees),
            }
            for interval in summary.intervals
        ],
        "total_profit_before_fees": str(summary.total_profit_before_fees),
        "total_profit_after_fees": str(summary.total_profit_after_fees),
    }


def summary_from_json(payload: dict[str, Any]) -> PNLSummary:
    intervals_payload = payload.get("intervals", [])
    intervals: list[IntervalMetrics] = []
    for item in intervals_payload:
        intervals.append(
            IntervalMetrics(
                key=str(item.get("key", "")),
                label=str(item.get("label", "")),
                profit_before_fees=Decimal(item.get("profit_before_fees", "0")),
                maker_volume=Decimal(item.get("maker_volume", "0")),
                taker_volume=Decimal(item.get("taker_volume", "0")),
                fee_total=Decimal(item.get("fee_total", "0")),
                profit_after_fees=Decimal(item.get("profit_after_fees", "0")),
            )
        )
    total_before = Decimal(payload.get("total_profit_before_fees", "0"))
    total_after = Decimal(payload.get("total_profit_after_fees", "0"))
    return PNLSummary(
        intervals=intervals,
        total_profit_before_fees=total_before,
        total_profit_after_fees=total_after,
    )


def _summarise_trades(trades: Sequence[TradeSnapshot], *, now: datetime) -> PNLSummary:
    entries = _build_entries(trades)

    intervals: list[IntervalMetrics] = []
    for key, label, delta in _timeframes():
        start = _effective_start(now, delta)
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


async def _load_trades_from_api(
    client: CoinbaseClient,
    *,
    product_id: str,
    start_anchor: datetime,
) -> list[TradeSnapshot]:
    trades: list[TradeSnapshot] = []
    cursor: Optional[str] = None

    while True:
        payload = await client.list_fills(
            product_id=product_id,
            limit=200,
            cursor=cursor,
            return_payload=True,
        )
        fills = payload.get("fills", [])
        if not fills:
            break

        stop_pagination = False
        for fill in fills:
            if fill.get("product_id") and fill.get("product_id") != product_id:
                continue

            ts = parse_datetime(fill.get("trade_time"))
            if ts is None:
                continue
            ts = _ensure_aware(ts)
            if ts < start_anchor:
                stop_pagination = True
                continue

            side = parse_side(fill.get("order_side") or fill.get("side"))
            size = parse_decimal(fill.get("size") or fill.get("base_size"))
            price = parse_decimal(fill.get("price") or fill.get("unit_price") or fill.get("average_price"))
            if size is None or price is None:
                continue
            if size <= 0 or price <= 0:
                continue

            liquidity = str(fill.get("liquidity_indicator") or fill.get("liquidity") or "").upper()
            post_only = liquidity == "MAKER"

            trades.append(
                TradeSnapshot(
                    timestamp=ts,
                    side=side,
                    price=price,
                    size=size,
                    post_only=post_only,
                )
            )

        cursor = payload.get("cursor")
        if not cursor or stop_pagination:
            break

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

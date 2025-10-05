from __future__ import annotations

import hashlib
import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterable, Mapping, Optional, Sequence

from app.coinbase.client import CoinbaseClient
from app.coinbase.exec import parse_decimal, parse_side, parse_datetime
from app import pnl_native
from app.db import crud, models
from app.db.session import session_scope


MAKER_FEE_RATE = Decimal("0.0025")
TAKER_FEE_RATE = Decimal("0.0015")
CUTOFF_TS = datetime(2025, 9, 1, tzinfo=timezone.utc)

logger = logging.getLogger("dashboard.pnl")


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


def _model_to_snapshot(model: models.PnLTrade) -> TradeSnapshot:
    return TradeSnapshot(
        timestamp=_ensure_aware(model.trade_time),
        side=model.side,
        price=model.price,
        size=model.size,
        post_only=bool(model.post_only),
    )


def _record_to_snapshot(record: crud.PnLTradeRecord) -> TradeSnapshot:
    return TradeSnapshot(
        timestamp=_ensure_aware(record.trade_time),
        side=record.side,
        price=record.price,
        size=record.size,
        post_only=record.post_only,
    )


async def calculate_pnl_summary(
    client: CoinbaseClient,
    *,
    product_id: str,
    now: Optional[datetime] = None,
) -> PNLSummary:
    """Hydrate PnL summary using Coinbase fills since 2025."""

    aware_now = _ensure_aware(now or datetime.now(timezone.utc))
    with session_scope() as session:
        cached_models = crud.list_pnl_trades(
            session,
            product_id=product_id,
            start_ts=CUTOFF_TS,
        )
        cached_snapshots = [_model_to_snapshot(model) for model in cached_models]
        known_fill_ids = {model.fill_id for model in cached_models}

    new_records, new_snapshots = await _load_trades_from_api(
        client,
        product_id=product_id,
        start_anchor=CUTOFF_TS,
        known_fill_ids=known_fill_ids,
    )

    if new_records:
        with session_scope() as session:
            inserted = crud.upsert_pnl_trades(session, new_records)
        if inserted:
            logger.info("Cached %s new PnL trades", inserted)

    if new_snapshots:
        cached_snapshots.extend(new_snapshots)

    cached_snapshots.sort(key=lambda trade: trade.timestamp)
    return summarise_trades(cached_snapshots, now=aware_now)


def summarise_trades(
    trades: Sequence[TradeSnapshot],
    *,
    now: Optional[datetime] = None,
) -> PNLSummary:
    """Summarise already-fetched trades into interval metrics."""

    aware_now = _ensure_aware(now or datetime.now(timezone.utc))
    ordered = sorted(trades, key=lambda trade: trade.timestamp)
    native_payload = _summarise_trades_native(ordered, now=aware_now)
    if native_payload is not None:
        return summary_from_json(native_payload)
    return _summarise_trades_python(ordered, now=aware_now)


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


def _summarise_trades_native(
    trades: Sequence[TradeSnapshot],
    *,
    now: datetime,
) -> Optional[dict[str, Any]]:
    if not pnl_native.native_available():
        return None
    payload = [_trade_to_native(trade) for trade in trades]
    if not payload:
        # No trades means the native module can short circuit with an empty payload.
        # We still call into native if available to keep behaviour aligned.
        payload = []

    result = pnl_native.summarise_trades(
        payload,
        list(_native_interval_specs()),
        now_timestamp_us=_to_microseconds(now),
        cutoff_timestamp_us=_to_microseconds(CUTOFF_TS),
        maker_fee_rate=str(MAKER_FEE_RATE),
        taker_fee_rate=str(TAKER_FEE_RATE),
    )
    return result


def _trade_to_native(trade: TradeSnapshot) -> Mapping[str, Any]:
    return {
        "timestamp_us": _to_microseconds(trade.timestamp),
        "side": trade.side.value,
        "price": str(trade.price),
        "size": str(trade.size),
        "post_only": trade.post_only,
    }


def _native_interval_specs() -> Iterable[Mapping[str, Any]]:
    for key, label, delta in _timeframes():
        yield {
            "key": key,
            "label": label,
            "delta_seconds": int(delta.total_seconds()) if delta else None,
        }


def _to_microseconds(ts: datetime) -> int:
    aware = _ensure_aware(ts)
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    delta = aware - epoch
    return delta.days * 86_400_000_000 + delta.seconds * 1_000_000 + delta.microseconds


def _summarise_trades_python(trades: Sequence[TradeSnapshot], *, now: datetime) -> PNLSummary:
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
    known_fill_ids: set[str],
) -> tuple[list[crud.PnLTradeRecord], list[TradeSnapshot]]:
    records: list[crud.PnLTradeRecord] = []
    snapshots: list[TradeSnapshot] = []
    cursor: Optional[str] = None
    seen_fill_ids = set(known_fill_ids)

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

            fill_id = _extract_fill_identifier(fill)
            if fill_id is None:
                continue
            if fill_id in seen_fill_ids:
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

            order_id = fill.get("order_id")
            if order_id is not None:
                order_id = str(order_id)

            record = crud.PnLTradeRecord(
                fill_id=fill_id,
                order_id=order_id,
                product_id=product_id,
                trade_time=ts,
                side=side,
                price=price,
                size=size,
                post_only=post_only,
                raw_json=fill,
            )
            records.append(record)
            snapshots.append(_record_to_snapshot(record))
            seen_fill_ids.add(fill_id)

        cursor = payload.get("cursor")
        if not cursor or stop_pagination:
            break

    snapshots.sort(key=lambda trade: trade.timestamp)
    return records, snapshots


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


def _extract_fill_identifier(fill: Mapping[str, Any]) -> Optional[str]:
    for key in ("fill_id", "entry_id", "order_fill_id", "trade_id"):
        value = fill.get(key)
        if value:
            return str(value)

    order_id = str(fill.get("order_id") or "").strip()
    trade_time = str(fill.get("trade_time") or fill.get("time") or "").strip()
    price = str(fill.get("price") or fill.get("unit_price") or fill.get("average_price") or "").strip()
    size = str(fill.get("size") or fill.get("base_size") or "").strip()

    if not (order_id and trade_time and price and size):
        return None

    fingerprint = f"{order_id}:{trade_time}:{price}:{size}"
    return hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()

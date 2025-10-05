from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional

try:
    from ._pnl_rs import (  # type: ignore[attr-defined]
        process_orders_and_fills as _process_orders_and_fills,
        summarise_trades as _summarise_trades,
    )
except ModuleNotFoundError:  # pragma: no cover - native module optional
    _summarise_trades = None
    _process_orders_and_fills = None


def native_available() -> bool:
    return _summarise_trades is not None


def summarise_trades(
    trades: Iterable[Mapping[str, Any]],
    intervals: Iterable[Mapping[str, Any]],
    *,
    now_timestamp_us: int,
    cutoff_timestamp_us: int,
    maker_fee_rate: str,
    taker_fee_rate: str,
) -> Optional[dict[str, Any]]:
    if _summarise_trades is None:
        return None
    return _summarise_trades(
        list(trades),
        list(intervals),
        now_timestamp_us,
        cutoff_timestamp_us,
        maker_fee_rate,
        taker_fee_rate,
    )


def process_orders_and_fills(
    orders: Iterable[Mapping[str, Any]],
    fills: Iterable[Mapping[str, Any]],
    *,
    product_id: str,
) -> Optional[dict[str, Any]]:
    if _process_orders_and_fills is None:
        return None
    return _process_orders_and_fills(list(orders), list(fills), product_id)

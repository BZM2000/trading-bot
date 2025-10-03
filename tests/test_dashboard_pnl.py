from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app.dashboard import pnl
from app.db.models import OrderSide


def _ts(year: int, month: int, day: int, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, 0, 0, tzinfo=timezone.utc)


def test_summarise_trades_intervals() -> None:
    trades = [
        pnl.TradeSnapshot(timestamp=_ts(2025, 2, 1), side=OrderSide.BUY, price=Decimal("700"), size=Decimal("1"), post_only=True),
        pnl.TradeSnapshot(timestamp=_ts(2025, 3, 1), side=OrderSide.SELL, price=Decimal("900"), size=Decimal("1"), post_only=False),
        pnl.TradeSnapshot(timestamp=_ts(2025, 12, 28), side=OrderSide.BUY, price=Decimal("800"), size=Decimal("1"), post_only=False),
        pnl.TradeSnapshot(timestamp=_ts(2025, 12, 29), side=OrderSide.SELL, price=Decimal("900"), size=Decimal("1"), post_only=True),
        pnl.TradeSnapshot(timestamp=_ts(2026, 1, 1, 1), side=OrderSide.BUY, price=Decimal("1000"), size=Decimal("1"), post_only=True),
        pnl.TradeSnapshot(timestamp=_ts(2026, 1, 1, 2), side=OrderSide.SELL, price=Decimal("1100"), size=Decimal("1"), post_only=False),
        pnl.TradeSnapshot(timestamp=_ts(2026, 1, 1, 3), side=OrderSide.BUY, price=Decimal("1200"), size=Decimal("1"), post_only=False),
    ]

    summary = pnl.summarise_trades(trades, now=_ts(2026, 1, 2))

    keys = [interval.key for interval in summary.intervals]
    assert keys == ["24h", "7d", "30d", "365d", "all"]

    by_key = {interval.key: interval for interval in summary.intervals}

    assert by_key["24h"].profit_before_fees == Decimal("100")
    assert by_key["24h"].profit_after_fees == Decimal("94.05")
    assert by_key["24h"].maker_volume == Decimal("1000")
    assert by_key["24h"].taker_volume == Decimal("2300")

    assert by_key["7d"].profit_before_fees == Decimal("200")
    assert by_key["7d"].profit_after_fees == Decimal("190.6")

    assert by_key["30d"].profit_before_fees == Decimal("200")
    assert by_key["30d"].profit_after_fees == Decimal("190.6")

    assert by_key["365d"].profit_before_fees == Decimal("400")
    assert by_key["365d"].profit_after_fees == Decimal("387.5")

    assert summary.total_profit_before_fees == Decimal("400")
    assert summary.total_profit_after_fees == Decimal("387.5")


def test_summarise_trades_handles_empty() -> None:
    summary = pnl.summarise_trades((), now=_ts(2026, 1, 2))

    assert summary.total_profit_before_fees == Decimal("0")
    assert summary.total_profit_after_fees == Decimal("0")
    assert all(interval.profit_before_fees == Decimal("0") for interval in summary.intervals)
    assert all(interval.profit_after_fees == Decimal("0") for interval in summary.intervals)

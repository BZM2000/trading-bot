from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.dashboard import pnl
from app.db import models
from app.db.models import OrderSide, OrderStatus


def _make_order(
    *,
    order_id: str,
    ts: datetime,
    side: OrderSide,
    price: str,
    size: str,
    post_only: bool,
) -> models.ExecutedOrder:
    return models.ExecutedOrder(
        order_id=order_id,
        ts_submitted=ts,
        ts_filled=ts,
        side=side,
        limit_price=Decimal(price),
        base_size=Decimal(size),
        status=OrderStatus.FILLED,
        filled_size=Decimal(size),
        client_order_id=f"client-{order_id}",
        end_time=ts,
        product_id="ETH-USDC",
        stop_price=None,
        post_only=post_only,
    )


def test_calculate_pnl_summary_intervals() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)

    try:
        with Session() as session:
            orders = [
                _make_order(
                    order_id="maker-buy",
                    ts=datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc),
                    side=OrderSide.BUY,
                    price="1000",
                    size="1",
                    post_only=True,
                ),
                _make_order(
                    order_id="taker-sell",
                    ts=datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc),
                    side=OrderSide.SELL,
                    price="1100",
                    size="1",
                    post_only=False,
                ),
                _make_order(
                    order_id="maker-sell-week",
                    ts=datetime(2025, 12, 28, 0, 0, tzinfo=timezone.utc),
                    side=OrderSide.SELL,
                    price="900",
                    size="1",
                    post_only=True,
                ),
                _make_order(
                    order_id="taker-buy-month",
                    ts=datetime(2025, 12, 5, 0, 0, tzinfo=timezone.utc),
                    side=OrderSide.BUY,
                    price="800",
                    size="1",
                    post_only=False,
                ),
                _make_order(
                    order_id="maker-sell-year",
                    ts=datetime(2025, 2, 1, 0, 0, tzinfo=timezone.utc),
                    side=OrderSide.SELL,
                    price="700",
                    size="1",
                    post_only=True,
                ),
                _make_order(
                    order_id="ignored-2024",
                    ts=datetime(2024, 12, 31, 0, 0, tzinfo=timezone.utc),
                    side=OrderSide.SELL,
                    price="1000",
                    size="1",
                    post_only=True,
                ),
            ]
            session.add_all(orders)
            session.commit()

        with Session() as session:
            summary = pnl.calculate_pnl_summary(
                session,
                product_id="ETH-USDC",
                now=datetime(2026, 1, 2, 0, 0, tzinfo=timezone.utc),
            )

        keys = [interval.key for interval in summary.intervals]
        assert keys == ["24h", "7d", "30d", "365d", "all"]

        by_key = {interval.key: interval for interval in summary.intervals}

        assert by_key["24h"].profit_before_fees == Decimal("100")
        assert by_key["24h"].profit_after_fees == Decimal("95.8500")

        assert by_key["7d"].profit_before_fees == Decimal("1000")
        assert by_key["7d"].profit_after_fees == Decimal("993.6000")

        assert by_key["30d"].profit_before_fees == Decimal("200")
        assert by_key["30d"].profit_after_fees == Decimal("192.4000")

        assert by_key["365d"].profit_before_fees == Decimal("900")
        assert by_key["365d"].profit_after_fees == Decimal("890.6500")

        assert summary.total_profit_before_fees == Decimal("900")
        assert summary.total_profit_after_fees == Decimal("890.6500")
    finally:
        engine.dispose()


def test_calculate_pnl_summary_handles_no_orders() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)

    try:
        with Session() as session:
            summary = pnl.calculate_pnl_summary(
                session,
                product_id="ETH-USDC",
                now=datetime(2026, 1, 2, 0, 0, tzinfo=timezone.utc),
            )

        assert summary.total_profit_before_fees == Decimal("0")
        assert summary.total_profit_after_fees == Decimal("0")
        assert all(interval.profit_before_fees == Decimal("0") for interval in summary.intervals)
        assert all(interval.profit_after_fees == Decimal("0") for interval in summary.intervals)
    finally:
        engine.dispose()


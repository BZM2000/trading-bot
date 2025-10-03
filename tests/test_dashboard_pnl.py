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
    client_order_id: str | None = None,
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
        client_order_id=client_order_id or f"client-{order_id}",
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
                    order_id="buy-feb",
                    ts=datetime(2025, 2, 1, 0, 0, tzinfo=timezone.utc),
                    side=OrderSide.BUY,
                    price="700",
                    size="1",
                    post_only=True,
                    client_order_id="0123456789abcdef0123456789abcdef",
                ),
                _make_order(
                    order_id="sell-mar",
                    ts=datetime(2025, 3, 1, 0, 0, tzinfo=timezone.utc),
                    side=OrderSide.SELL,
                    price="900",
                    size="1",
                    post_only=False,
                    client_order_id="fedcba9876543210fedcba9876543210",
                ),
                _make_order(
                    order_id="buy-dec",
                    ts=datetime(2025, 12, 28, 0, 0, tzinfo=timezone.utc),
                    side=OrderSide.BUY,
                    price="800",
                    size="1",
                    post_only=False,
                    client_order_id="00112233445566778899aabbccddeeff",
                ),
                _make_order(
                    order_id="sell-dec",
                    ts=datetime(2025, 12, 29, 0, 0, tzinfo=timezone.utc),
                    side=OrderSide.SELL,
                    price="900",
                    size="1",
                    post_only=True,
                    client_order_id="ffeeddccbbaa99887766554433221100",
                ),
                _make_order(
                    order_id="buy-jan",
                    ts=datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc),
                    side=OrderSide.BUY,
                    price="1000",
                    size="1",
                    post_only=True,
                    client_order_id="11111111111111111111111111111111",
                ),
                _make_order(
                    order_id="sell-jan",
                    ts=datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc),
                    side=OrderSide.SELL,
                    price="1100",
                    size="1",
                    post_only=False,
                    client_order_id="22222222222222222222222222222222",
                ),
                _make_order(
                    order_id="buy-open",
                    ts=datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc),
                    side=OrderSide.BUY,
                    price="1200",
                    size="1",
                    post_only=False,
                    client_order_id="33333333333333333333333333333333",
                ),
                _make_order(
                    order_id="ignored-2024",
                    ts=datetime(2024, 12, 31, 0, 0, tzinfo=timezone.utc),
                    side=OrderSide.SELL,
                    price="1000",
                    size="1",
                    post_only=True,
                    client_order_id="44444444444444444444444444444444",
                ),
                _make_order(
                    order_id="manual",
                    ts=datetime(2026, 1, 1, 4, 0, tzinfo=timezone.utc),
                    side=OrderSide.SELL,
                    price="2000",
                    size="1",
                    post_only=False,
                    client_order_id="manual-order",
                ),
            ]
            session.add_all(orders)
            session.commit()

        with Session() as session:
            summary = pnl.calculate_pnl_summary(
                session,
                product_id="ETH-USDC",
                now=datetime(2026, 1, 2, 0, 0, tzinfo=timezone.utc),
                start_anchor=datetime(2025, 12, 1, 0, 0, tzinfo=timezone.utc),
            )

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

        assert by_key["365d"].profit_before_fees == Decimal("200")
        assert by_key["365d"].profit_after_fees == Decimal("190.6")

        assert summary.total_profit_before_fees == Decimal("200")
        assert summary.total_profit_after_fees == Decimal("190.6")
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

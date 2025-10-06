from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from app.coinbase import OrderType, PlannedOrder
from app.coinbase.validators import ProductConstraints
from app.db.models import OrderSide
from app.scheduler.orchestration import SchedulerOrchestrator


CONSTRAINTS = ProductConstraints(
    price_increment=Decimal("0.01"),
    size_increment=Decimal("0.0001"),
    min_size=Decimal("0.001"),
    min_distance_pct=Decimal("0.001"),
)


def _planned_order(*, side: OrderSide, limit_price: Decimal, base_size: Decimal, post_only: bool, order_type: OrderType) -> PlannedOrder:
    return PlannedOrder(
        side=side,
        limit_price=limit_price,
        base_size=base_size,
        end_time=datetime.now(timezone.utc),
        post_only=post_only,
        order_type=order_type,
    )


def test_apply_quote_buffer_scales_maker_order_with_cushion() -> None:
    orchestrator = SchedulerOrchestrator(settings=SimpleNamespace(product_id="ETH-USDC"))
    planned = [
        _planned_order(
            side=OrderSide.BUY,
            limit_price=Decimal("2000"),
            base_size=Decimal("0.045"),
            post_only=True,
            order_type=OrderType.LIMIT,
        )
    ]
    balances = {"USDC": {"available": "90"}}

    adjusted = orchestrator._apply_quote_buffer(planned, balances, CONSTRAINTS)

    assert adjusted[0].base_size == Decimal("0.0448")


def test_apply_quote_buffer_scales_taker_order_with_cushion() -> None:
    orchestrator = SchedulerOrchestrator(settings=SimpleNamespace(product_id="ETH-USDC"))
    planned = [
        _planned_order(
            side=OrderSide.BUY,
            limit_price=Decimal("2000"),
            base_size=Decimal("0.045"),
            post_only=False,
            order_type=OrderType.LIMIT,
        )
    ]
    balances = {"USDC": {"available": "90"}}

    adjusted = orchestrator._apply_quote_buffer(planned, balances, CONSTRAINTS)

    assert adjusted[0].base_size == Decimal("0.0446")


def test_apply_quote_buffer_drops_when_no_available_usdc() -> None:
    orchestrator = SchedulerOrchestrator(settings=SimpleNamespace(product_id="ETH-USDC"))
    planned = [
        _planned_order(
            side=OrderSide.BUY,
            limit_price=Decimal("2000"),
            base_size=Decimal("0.01"),
            post_only=True,
            order_type=OrderType.LIMIT,
        )
    ]
    balances = {"USDC": {"available": "0"}}

    adjusted = orchestrator._apply_quote_buffer(planned, balances, CONSTRAINTS)

    assert adjusted == []


def test_apply_quote_buffer_preserves_sell_orders() -> None:
    orchestrator = SchedulerOrchestrator(settings=SimpleNamespace(product_id="ETH-USDC"))
    planned = [
        _planned_order(
            side=OrderSide.SELL,
            limit_price=Decimal("2000"),
            base_size=Decimal("0.02"),
            post_only=True,
            order_type=OrderType.LIMIT,
        )
    ]
    balances = {"USDC": {"available": "5"}}

    adjusted = orchestrator._apply_quote_buffer(planned, balances, CONSTRAINTS)

    assert adjusted == planned

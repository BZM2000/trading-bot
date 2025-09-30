from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.coinbase.exec import ExecutionService, OrderType, PlannedOrder, resolve_submitted_time
from app.coinbase.validators import ProductConstraints
from app.db.models import OrderSide


class DummyClient:
    async def create_order(self, payload):  # pragma: no cover - unused in tests
        return payload


@pytest.fixture
def constraints() -> ProductConstraints:
    return ProductConstraints(
        price_increment=Decimal("0.01"),
        size_increment=Decimal("0.001"),
        min_size=Decimal("0.01"),
        min_distance_pct=Decimal("0.01"),
    )


@pytest.fixture
def execution_service(constraints: ProductConstraints) -> ExecutionService:
    return ExecutionService(DummyClient(), product_id="ETH-USDC", constraints=constraints)


def test_validate_limit_order(execution_service: ExecutionService) -> None:
    end_time = datetime.now(timezone.utc) + timedelta(hours=2)
    order = PlannedOrder(
        side=OrderSide.BUY,
        limit_price=Decimal("1979.991"),
        base_size=Decimal("0.05"),
        end_time=end_time,
        post_only=True,
    )

    validated = execution_service._validate_orders([order], mid_price=Decimal("2000"))
    assert len(validated) == 1
    assert validated[0].limit_price == Decimal("1979.99")
    assert validated[0].stop_price is None
    assert validated[0].post_only is True


def test_validate_stop_limit_order(execution_service: ExecutionService) -> None:
    end_time = datetime.now(timezone.utc) + timedelta(hours=2)
    order = PlannedOrder(
        side=OrderSide.BUY,
        limit_price=Decimal("2060"),
        base_size=Decimal("0.05"),
        end_time=end_time,
        post_only=False,
        stop_price=Decimal("2050.001"),
        order_type=OrderType.STOP_LIMIT,
    )

    validated = execution_service._validate_orders([order], mid_price=Decimal("2000"))
    assert len(validated) == 1
    assert validated[0].limit_price == Decimal("2060")
    assert validated[0].stop_price == Decimal("2050.01")
    assert validated[0].post_only is False


def test_validate_stop_limit_enforces_direction(execution_service: ExecutionService) -> None:
    end_time = datetime.now(timezone.utc) + timedelta(hours=2)
    order = PlannedOrder(
        side=OrderSide.BUY,
        limit_price=Decimal("1995"),
        base_size=Decimal("0.05"),
        end_time=end_time,
        stop_price=Decimal("1980"),
        order_type=OrderType.STOP_LIMIT,
    )

    with pytest.raises(ValueError):
        execution_service._validate_orders([order], mid_price=Decimal("2000"))


def test_stop_limit_payload_build(execution_service: ExecutionService) -> None:
    end_time = datetime.now(timezone.utc) + timedelta(hours=2)
    order = PlannedOrder(
        side=OrderSide.SELL,
        limit_price=Decimal("1950"),
        base_size=Decimal("0.1"),
        end_time=end_time,
        post_only=False,
        stop_price=Decimal("1980"),
        order_type=OrderType.STOP_LIMIT,
    )

    payload = execution_service._build_payload(order)
    config = payload["order_configuration"]["stop_limit_stop_limit_gtd"]
    assert config["stop_price"] == "1980"
    assert config["limit_price"] == "1950"
    assert config["stop_direction"] == "STOP_DIRECTION_STOP_DOWN"


def test_market_order_validation_and_payload(execution_service: ExecutionService) -> None:
    end_time = datetime.now(timezone.utc) + timedelta(hours=2)
    order = PlannedOrder(
        side=OrderSide.BUY,
        limit_price=Decimal("2000"),
        base_size=Decimal("0.05"),
        end_time=end_time,
        post_only=False,
        stop_price=None,
        order_type=OrderType.MARKET,
    )

    validated = execution_service._validate_orders([order], mid_price=Decimal("2050"))
    assert len(validated) == 1
    assert validated[0].order_type is OrderType.MARKET
    assert validated[0].post_only is False

    payload = execution_service._build_payload(validated[0])
    assert "market_market_ioc" in payload["order_configuration"]
    market_cfg = payload["order_configuration"]["market_market_ioc"]
    assert Decimal(market_cfg["base_size"]) == Decimal("0.05")


def test_resolve_submitted_time_uses_created_when_missing_submitted() -> None:
    created = "2024-07-12T09:15:30Z"
    order = {"created_time": created}

    resolved = resolve_submitted_time(order)

    assert resolved == datetime(2024, 7, 12, 9, 15, 30, tzinfo=timezone.utc)


def test_resolve_submitted_time_prefers_submitted_timestamp() -> None:
    submitted = "2024-07-12T10:00:00Z"
    created = "2024-07-11T09:15:30Z"
    order = {"submitted_time": submitted, "created_time": created}

    resolved = resolve_submitted_time(order)

    assert resolved == datetime(2024, 7, 12, 10, 0, 0, tzinfo=timezone.utc)


def test_resolve_submitted_time_uses_order_placed_when_available() -> None:
    placed = "2024-07-10T08:30:15Z"
    order = {"order_placed_time": placed}

    resolved = resolve_submitted_time(order)

    assert resolved == datetime(2024, 7, 10, 8, 30, 15, tzinfo=timezone.utc)

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.coinbase.exec import ExecutionService, PlannedOrder
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
    )

    payload = execution_service._build_payload(order)
    config = payload["order_configuration"]["stop_limit_stop_limit_gtd"]
    assert config["stop_price"] == "1980"
    assert config["limit_price"] == "1950"
    assert config["stop_direction"] == "STOP_DIRECTION_STOP_DOWN"

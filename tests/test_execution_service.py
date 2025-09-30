from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.coinbase.exec import ExecutionService, OrderType, PlannedOrder, resolve_submitted_time
from app.coinbase.validators import ProductConstraints
from app.db import crud, models
from app.db.models import OrderSide, OrderStatus


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

    resolved, inferred = resolve_submitted_time(order, [], None)

    assert resolved == datetime(2024, 7, 12, 9, 15, 30, tzinfo=timezone.utc)
    assert inferred is False


def test_resolve_submitted_time_prefers_submitted_timestamp() -> None:
    submitted = "2024-07-12T10:00:00Z"
    created = "2024-07-11T09:15:30Z"
    order = {"submitted_time": submitted, "created_time": created}

    resolved, inferred = resolve_submitted_time(order, [], None)

    assert resolved == datetime(2024, 7, 12, 10, 0, 0, tzinfo=timezone.utc)
    assert inferred is False


def test_resolve_submitted_time_uses_order_placed_when_available() -> None:
    placed = "2024-07-10T08:30:15Z"
    order = {"order_placed_time": placed}

    resolved, inferred = resolve_submitted_time(order, [], None)

    assert resolved == datetime(2024, 7, 10, 8, 30, 15, tzinfo=timezone.utc)
    assert inferred is False


def test_resolve_submitted_time_derives_from_fill_times() -> None:
    fills = [{"trade_time": "2024-07-09T01:02:03Z"}, {"trade_time": "2024-07-09T01:03:04Z"}]

    resolved, inferred = resolve_submitted_time({}, fills, None)

    assert resolved == datetime(2024, 7, 9, 1, 2, 3, tzinfo=timezone.utc)
    assert inferred is False


def test_resolve_submitted_time_uses_completed_time_as_last_resort() -> None:
    completed = datetime(2024, 7, 8, 5, 6, 7, tzinfo=timezone.utc)

    resolved, inferred = resolve_submitted_time({}, [], completed)

    assert resolved == completed
    assert inferred is False


def test_resolve_submitted_time_marks_generated_timestamp(monkeypatch) -> None:
    fixed = datetime(2024, 7, 7, 12, 0, 0, tzinfo=timezone.utc)

    class DummyDateTime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return fixed if tz else fixed.replace(tzinfo=None)

    monkeypatch.setattr("app.coinbase.exec.datetime", DummyDateTime)

    resolved, inferred = resolve_submitted_time({}, [], None)

    assert resolved == fixed
    assert inferred is True


def test_upsert_executed_orders_skips_inferred_submitted_update() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)

    original_ts = datetime(2024, 7, 5, 12, 0, tzinfo=timezone.utc)
    with Session() as session:
        order = models.ExecutedOrder(
            order_id="order-1",
            ts_submitted=original_ts,
            ts_filled=None,
            side=OrderSide.BUY,
            limit_price=Decimal("1000"),
            base_size=Decimal("0.5"),
            status=OrderStatus.FILLED,
            filled_size=Decimal("0.5"),
            client_order_id="client-1",
            end_time=original_ts + timedelta(hours=1),
            product_id="ETH-USDC",
            stop_price=None,
        )
        session.add(order)
        session.commit()

        record = crud.ExecutedOrderRecord(
            order_id="order-1",
            ts_submitted=original_ts + timedelta(minutes=5),
            ts_filled=None,
            side=OrderSide.BUY,
            limit_price=Decimal("1000"),
            base_size=Decimal("0.5"),
            status=OrderStatus.FILLED,
            filled_size=Decimal("0.5"),
            client_order_id="client-1",
            end_time=original_ts + timedelta(hours=1),
            product_id="ETH-USDC",
            stop_price=None,
            ts_submitted_inferred=True,
        )

        crud.upsert_executed_orders(session, [record])

        refreshed = session.get(models.ExecutedOrder, "order-1")
        assert refreshed is not None
        assert refreshed.ts_submitted == (original_ts.replace(tzinfo=None))
        assert refreshed.ts_submitted != (original_ts + timedelta(minutes=5)).replace(tzinfo=None)

    engine.dispose()

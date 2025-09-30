from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.coinbase.exec import OrderType
from app.db.models import OrderSide
from app.llm.schemas import Model3Order, Model3Response


def test_model3_response_parses_and_creates_planned_orders() -> None:
    payload = {
        "orders": [
            {
                "side": "BUY",
                "limit_price": "2015.5",
                "base_size": "0.05",
                "post_only": True,
                "order_type": "limit",
                "note": "Test order",
            }
        ],
        "warnings": "example",
    }

    response = Model3Response.model_validate(payload)
    planned = response.to_planned_orders()
    assert len(planned) == 1
    order = planned[0]
    assert order.side == OrderSide.BUY
    assert order.limit_price == Decimal("2015.5")
    assert order.post_only is True
    assert order.stop_price is None
    assert order.order_type is OrderType.LIMIT


def test_model3_rejects_duplicate_sides() -> None:
    with pytest.raises(ValidationError):
        Model3Response.model_validate(
            {
                "orders": [
                    {"side": "BUY", "limit_price": "2000", "base_size": "0.1"},
                    {"side": "BUY", "limit_price": "1990", "base_size": "0.2"},
                ]
            }
        )


def test_model3_order_requires_positive_values() -> None:
    with pytest.raises(ValidationError):
        Model3Order.model_validate({"side": "SELL", "limit_price": 0, "base_size": -1})


def test_model3_stop_limit_round_trip() -> None:
    payload = {
        "orders": [
            {
                "side": "SELL",
                "limit_price": "2100",
                "base_size": "0.08",
                "order_type": "stop_limit",
                "stop_price": "2050",
            }
        ]
    }

    response = Model3Response.model_validate(payload)
    planned = response.to_planned_orders()
    planned_order = planned[0]
    assert planned_order.side == OrderSide.SELL
    assert planned_order.stop_price == Decimal("2050")
    assert planned_order.post_only is False
    assert planned_order.order_type is OrderType.STOP_LIMIT


def test_model3_stop_limit_requires_stop_price() -> None:
    with pytest.raises(ValidationError):
        Model3Order.model_validate(
            {
                "side": "BUY",
                "limit_price": "2000",
                "base_size": "0.05",
                "order_type": "stop_limit",
            }
        )


def test_model3_limit_rejects_stop_price() -> None:
    with pytest.raises(ValidationError):
        Model3Order.model_validate(
            {
                "side": "BUY",
                "limit_price": "2000",
                "base_size": "0.05",
                "order_type": "limit",
                "stop_price": "2010",
            }
        )


def test_model3_market_order_rejects_post_only_true() -> None:
    with pytest.raises(ValidationError):
        Model3Order.model_validate(
            {
                "side": "BUY",
                "limit_price": "2000",
                "base_size": "0.05",
                "order_type": "market",
                "post_only": True,
            }
        )


def test_model3_market_order_defaults_post_only_false() -> None:
    payload = {
        "orders": [
            {
                "side": "BUY",
                "limit_price": "2005.25",
                "base_size": "0.04",
                "order_type": "market",
            }
        ]
    }

    response = Model3Response.model_validate(payload)
    planned = response.to_planned_orders()
    assert len(planned) == 1
    order = planned[0]
    assert order.order_type is OrderType.MARKET
    assert order.post_only is False
    assert order.stop_price is None

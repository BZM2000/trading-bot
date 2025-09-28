from decimal import Decimal

import pytest
from pydantic import ValidationError

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

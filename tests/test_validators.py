from decimal import Decimal

import pytest

from app.coinbase.validators import (
    ProductConstraints,
    ensure_min_size,
    enforce_min_distance,
    round_price,
    round_size,
)
from app.db.models import OrderSide


CONSTRAINTS = ProductConstraints(
    price_increment=Decimal("0.01"),
    size_increment=Decimal("0.001"),
    min_size=Decimal("0.01"),
    min_distance_pct=Decimal("0.0015"),
)


def test_round_price_buy_rounds_down() -> None:
    price = Decimal("2015.678")
    rounded = round_price(price, CONSTRAINTS, OrderSide.BUY)
    assert rounded == Decimal("2015.67")


def test_round_price_sell_rounds_up() -> None:
    price = Decimal("2015.671")
    rounded = round_price(price, CONSTRAINTS, OrderSide.SELL)
    assert rounded == Decimal("2015.68")


def test_round_size_applies_increment() -> None:
    size = Decimal("0.1234")
    rounded = round_size(size, CONSTRAINTS)
    assert rounded == Decimal("0.123")


def test_ensure_min_size_raises_when_too_small() -> None:
    with pytest.raises(ValueError):
        ensure_min_size(Decimal("0.0005"), CONSTRAINTS)


def test_enforce_min_distance_buy_violation() -> None:
    mid_price = Decimal("2000")
    price = Decimal("1999.8")  # 0.2 away, threshold is 3.0
    with pytest.raises(ValueError):
        enforce_min_distance(price, mid_price, CONSTRAINTS, OrderSide.BUY)


def test_enforce_min_distance_sell_violation() -> None:
    mid_price = Decimal("2000")
    price = Decimal("2000.1")
    with pytest.raises(ValueError):
        enforce_min_distance(price, mid_price, CONSTRAINTS, OrderSide.SELL)


def test_enforce_min_distance_allows_valid_prices() -> None:
    mid_price = Decimal("2000")
    buy_price = Decimal("1996")  # 4 away
    sell_price = Decimal("2006")
    enforce_min_distance(buy_price, mid_price, CONSTRAINTS, OrderSide.BUY)
    enforce_min_distance(sell_price, mid_price, CONSTRAINTS, OrderSide.SELL)

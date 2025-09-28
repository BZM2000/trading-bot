from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR

from app.coinbase.client import Product
from app.db.models import OrderSide


def _increment_decimal(value: str) -> Decimal:
    return Decimal(value)


@dataclass(slots=True)
class ProductConstraints:
    price_increment: Decimal
    size_increment: Decimal
    min_size: Decimal
    min_distance_pct: Decimal

    @classmethod
    def from_product(cls, product: Product, min_distance_pct: Decimal) -> "ProductConstraints":
        return cls(
            price_increment=_increment_decimal(product.quote_increment),
            size_increment=_increment_decimal(product.base_increment),
            min_size=_increment_decimal(product.base_min_size),
            min_distance_pct=min_distance_pct,
        )


def round_price(price: Decimal, constraints: ProductConstraints, side: OrderSide) -> Decimal:
    increment = constraints.price_increment
    if increment == 0:
        return price
    quant = price / increment
    if side == OrderSide.BUY:
        quant = quant.to_integral_value(rounding=ROUND_FLOOR)
    else:
        quant = quant.to_integral_value(rounding=ROUND_CEILING)
    rounded = quant * increment
    return rounded.quantize(increment)


def round_size(size: Decimal, constraints: ProductConstraints) -> Decimal:
    increment = constraints.size_increment
    if increment == 0:
        return size
    quant = (size / increment).to_integral_value(rounding=ROUND_DOWN)
    rounded = quant * increment
    return rounded.quantize(increment)


def ensure_min_size(size: Decimal, constraints: ProductConstraints) -> Decimal:
    rounded_size = round_size(size, constraints)
    if rounded_size < constraints.min_size:
        raise ValueError(f"Size {rounded_size} is below minimum {constraints.min_size}")
    return rounded_size


def enforce_min_distance(price: Decimal, mid_price: Decimal, constraints: ProductConstraints, side: OrderSide) -> None:
    threshold = mid_price * constraints.min_distance_pct
    if side == OrderSide.BUY and mid_price - price < threshold:
        raise ValueError("Buy order does not satisfy minimum distance from mid-price")
    if side == OrderSide.SELL and price - mid_price < threshold:
        raise ValueError("Sell order does not satisfy minimum distance from mid-price")

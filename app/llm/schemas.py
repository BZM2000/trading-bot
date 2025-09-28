from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.coinbase.exec import PlannedOrder
from app.db.models import OrderSide


class Model3Order(BaseModel):
    side: Literal["BUY", "SELL"] = Field(description="Order side")
    limit_price: Decimal = Field(gt=Decimal("0"), description="Limit price in quote currency")
    base_size: Decimal = Field(gt=Decimal("0"), description="Order size in base currency")
    post_only: bool = Field(default=True, description="Whether the order must remain maker-only")
    note: Optional[str] = Field(default=None, max_length=300, description="Short justification")


class Model3Response(BaseModel):
    orders: list[Model3Order] = Field(default_factory=list, max_length=2)
    warnings: Optional[str] = Field(default=None, description="Any validation notes")

    @field_validator("orders")
    @classmethod
    def ensure_unique_sides(cls, value: list[Model3Order]) -> list[Model3Order]:
        sides = {order.side for order in value}
        if len(value) != len(sides):
            raise ValueError("Duplicate order sides detected")
        return value

    def to_planned_orders(self, *, end_time: Optional[datetime] = None) -> list[PlannedOrder]:
        end_time = end_time or datetime.now(timezone.utc) + timedelta(hours=2)
        return [
            PlannedOrder(
                side=OrderSide(order.side),
                limit_price=order.limit_price,
                base_size=order.base_size,
                post_only=order.post_only,
                end_time=end_time,
            )
            for order in self.orders
        ]


MODEL3_JSON_SCHEMA = Model3Response.model_json_schema(ref_template="#/$defs/{model}")

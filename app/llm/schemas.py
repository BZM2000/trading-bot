from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.coinbase.exec import PlannedOrder
from app.db.models import OrderSide


class Model3Order(BaseModel):
    model_config = ConfigDict(extra="forbid")
    side: Literal["BUY", "SELL"] = Field(description="Order side")
    limit_price: Decimal = Field(gt=Decimal("0"), description="Limit price in quote currency")
    base_size: Decimal = Field(gt=Decimal("0"), description="Order size in base currency")
    post_only: bool = Field(default=True, description="Whether the order must remain maker-only")
    note: Optional[str] = Field(default=None, max_length=300, description="Short justification")


class Model3Response(BaseModel):
    model_config = ConfigDict(extra="forbid")
    orders: list[Model3Order] = Field(default_factory=list, max_length=1)
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


def _ensure_required_flags(schema: dict[str, Any]) -> None:
    if not isinstance(schema, dict):
        return

    if schema.get("type") == "object":
        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            required = schema.setdefault("required", [])
            for key, subschema in properties.items():
                if key not in required:
                    required.append(key)
                _ensure_required_flags(subschema)

    if schema.get("type") == "array":
        items = schema.get("items")
        if isinstance(items, dict):
            _ensure_required_flags(items)

    for defs_key in ("$defs", "definitions"):
        definitions = schema.get(defs_key)
        if isinstance(definitions, dict):
            for subschema in definitions.values():
                _ensure_required_flags(subschema)

    if isinstance(schema.get("anyOf"), list):
        for option in schema["anyOf"]:
            _ensure_required_flags(option)


MODEL3_JSON_SCHEMA = Model3Response.model_json_schema(ref_template="#/$defs/{model}")
_ensure_required_flags(MODEL3_JSON_SCHEMA)

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional, Sequence

from sqlalchemy.orm import Session

from app.coinbase.client import CoinbaseClient
from app.coinbase.validators import (
    ProductConstraints,
    ensure_min_size,
    enforce_min_distance,
    enforce_stop_distance,
    round_price,
    round_stop_price,
)
from app.db import crud
from app.db.models import OrderSide, OrderStatus


class OrderType(str, Enum):
    LIMIT = "limit"
    STOP_LIMIT = "stop_limit"
    MARKET = "market"


@dataclass(slots=True)
class PlannedOrder:
    side: OrderSide
    limit_price: Decimal
    base_size: Decimal
    end_time: datetime
    post_only: bool = True
    stop_price: Optional[Decimal] = None
    order_type: OrderType = OrderType.LIMIT


@dataclass(slots=True)
class SyncResult:
    open_orders: list[crud.OpenOrderRecord]
    executed_orders: list[crud.ExecutedOrderRecord]
    changed_order_ids: set[str]


STATUS_MAP = {
    "OPEN": OrderStatus.OPEN,
    "NEW": OrderStatus.NEW,
    "FILLED": OrderStatus.FILLED,
    "CANCELLED": OrderStatus.CANCELLED,
    "EXPIRED": OrderStatus.EXPIRED,
}


class ExecutionService:
    def __init__(
        self,
        client: CoinbaseClient,
        *,
        product_id: str,
        constraints: ProductConstraints,
    ) -> None:
        self.client = client
        self.product_id = product_id
        self.constraints = constraints

    async def place_orders(self, planned_orders: Sequence[PlannedOrder], *, mid_price: Decimal) -> list[dict]:
        validated_orders = self._validate_orders(planned_orders, mid_price)
        responses = []
        for order in validated_orders:
            payload = self._build_payload(order)
            response = await self.client.create_order(payload)
            responses.append(response)
        return responses

    def _validate_orders(self, planned_orders: Sequence[PlannedOrder], mid_price: Decimal) -> list[PlannedOrder]:
        if len(planned_orders) == 0:
            return []
        if len(planned_orders) > 1:
            raise ValueError("At most one planned order is allowed")

        sides = {order.side for order in planned_orders}
        if len(planned_orders) != len(sides):
            raise ValueError("Duplicate order sides detected")

        validated: list[PlannedOrder] = []
        for order in planned_orders:
            size = ensure_min_size(order.base_size, self.constraints)

            if order.order_type == OrderType.MARKET:
                if order.stop_price is not None:
                    raise ValueError("Market orders cannot include a stop price")
                validated.append(
                    PlannedOrder(
                        side=order.side,
                        limit_price=order.limit_price,
                        base_size=size,
                        end_time=order.end_time,
                        post_only=False,
                        stop_price=None,
                        order_type=OrderType.MARKET,
                    )
                )
                continue

            if order.limit_price is None:
                raise ValueError("Limit price must be provided for limit and stop-limit orders")

            if order.order_type == OrderType.LIMIT and order.stop_price is not None:
                raise ValueError("Limit orders must omit stop price")

            if order.order_type == OrderType.STOP_LIMIT:
                if order.stop_price is None:
                    raise ValueError("Stop price must be provided for stop-limit orders")

                stop_price = round_stop_price(order.stop_price, self.constraints, order.side)
                limit_price = round_price(order.limit_price, self.constraints, order.side)
                enforce_stop_distance(stop_price, mid_price, self.constraints, order.side)

                if order.side == OrderSide.BUY and limit_price < stop_price:
                    raise ValueError("Buy stop-limit orders require limit price ≥ stop price")
                if order.side == OrderSide.SELL and limit_price > stop_price:
                    raise ValueError("Sell stop-limit orders require limit price ≤ stop price")

                validated.append(
                    PlannedOrder(
                        side=order.side,
                        limit_price=limit_price,
                        base_size=size,
                        end_time=order.end_time,
                        post_only=False,
                        stop_price=stop_price,
                        order_type=OrderType.STOP_LIMIT,
                    )
                )
                continue

            price = round_price(order.limit_price, self.constraints, order.side)
            enforce_min_distance(price, mid_price, self.constraints, order.side)
            validated.append(
                PlannedOrder(
                    side=order.side,
                    limit_price=price,
                    base_size=size,
                    end_time=order.end_time,
                    post_only=order.post_only,
                    stop_price=None,
                    order_type=OrderType.LIMIT,
                )
            )
        return validated

    def _build_payload(self, order: PlannedOrder) -> dict:
        client_order_id = uuid.uuid4().hex
        payload = {
            "client_order_id": client_order_id,
            "product_id": self.product_id,
            "side": order.side.value,
        }

        if order.order_type == OrderType.MARKET:
            payload["order_configuration"] = {
                "market_market_ioc": {
                    "base_size": str(order.base_size),
                }
            }
        elif order.order_type == OrderType.STOP_LIMIT:
            payload["order_configuration"] = {
                "stop_limit_stop_limit_gtd": {
                    "base_size": str(order.base_size),
                    "limit_price": str(order.limit_price),
                    "stop_price": str(order.stop_price),
                    "end_time": order.end_time.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "stop_direction": self._stop_direction(order),
                }
            }
        else:
            payload["order_configuration"] = {
                "limit_limit_gtd": {
                    "base_size": str(order.base_size),
                    "limit_price": str(order.limit_price),
                    "post_only": order.post_only,
                    "end_time": order.end_time.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                }
            }

        return payload

    async def sync_open_and_fills(self, session: Session, *, product_id: Optional[str] = None) -> SyncResult:
        product = product_id or self.product_id
        orders_payload = await self.client.list_orders(
            product_id=product,
            order_status=["OPEN", "FILLED", "CANCELLED", "EXPIRED"],
            limit=200,
        )
        fills_payload = await self.client.list_fills(product_id=product, limit=200)
        fills_by_order: dict[str, list[dict]] = {}
        for fill in fills_payload:
            order_id = fill.get("order_id")
            if not order_id:
                continue
            fills_by_order.setdefault(order_id, []).append(fill)

        open_records: list[crud.OpenOrderRecord] = []
        executed_records: list[crud.ExecutedOrderRecord] = []

        for order in orders_payload:
            order_id = order.get("order_id")
            if not order_id:
                continue
            status_str = (order.get("status") or order.get("order_status") or "").upper()
            status = STATUS_MAP.get(status_str, OrderStatus.NEW)
            config_type, config = self._extract_order_config(order)
            if config is None:
                continue

            submitted = parse_datetime(order.get("submitted_time")) or datetime.now(timezone.utc)
            client_order_id = order.get("client_order_id", "")
            side = parse_side(order.get("side"))

            fills = fills_by_order.get(order_id, [])
            filled_size = sum_fills(fills)
            completed_time = parse_datetime(order.get("completed_time")) if status != OrderStatus.OPEN else None
            if not completed_time and fills:
                completed_time = parse_datetime(fills[-1].get("trade_time"))

            base_size_value = config.get("base_size") or config.get("base_order_size")
            base_size = parse_decimal(base_size_value) or Decimal("0")
            if base_size == 0 and filled_size:
                base_size = filled_size

            if config_type == "market":
                limit_price = (
                    average_fill_price(fills)
                    or parse_decimal(order.get("average_filled_price"))
                    or Decimal("0")
                )
                stop_price = None
                end_time = completed_time or submitted
            else:
                limit_price = parse_decimal(config.get("limit_price")) or Decimal("0")
                stop_price = parse_decimal(config.get("stop_price"))
                end_time = (
                    parse_datetime(config.get("end_time"))
                    or parse_datetime(order.get("expire_time"))
                    or submitted
                )

            if status == OrderStatus.OPEN:
                open_records.append(
                    crud.OpenOrderRecord(
                        order_id=order_id,
                        side=side,
                        limit_price=limit_price,
                        base_size=base_size,
                        status=status,
                        client_order_id=client_order_id,
                        end_time=end_time,
                        product_id=product,
                        stop_price=stop_price,
                    )
                )

            executed_records.append(
                crud.ExecutedOrderRecord(
                    order_id=order_id,
                    ts_submitted=submitted,
                    ts_filled=completed_time,
                    side=side,
                    limit_price=limit_price,
                    base_size=base_size,
                    status=status,
                    filled_size=filled_size,
                    client_order_id=client_order_id,
                    end_time=end_time,
                    product_id=product,
                    stop_price=stop_price,
                )
            )

        crud.replace_open_orders(session, open_records)
        changed_ids = crud.upsert_executed_orders(session, executed_records)
        return SyncResult(
            open_orders=open_records,
            executed_orders=executed_records,
            changed_order_ids=changed_ids,
        )

    def _stop_direction(self, order: PlannedOrder) -> str:
        return "STOP_DIRECTION_STOP_UP" if order.side == OrderSide.BUY else "STOP_DIRECTION_STOP_DOWN"

    def _extract_order_config(self, order: dict) -> tuple[str, Optional[dict]]:
        config = order.get("order_configuration", {})
        if not isinstance(config, dict):
            return ("unknown", None)

        for key in ("limit_limit_gtd", "limit_limit_gtc"):
            value = config.get(key)
            if value:
                return ("limit", value)

        for key in ("stop_limit_stop_limit_gtd", "stop_limit_stop_limit_gtc"):
            value = config.get(key)
            if value:
                return ("stop_limit", value)

        for key in ("market_market_ioc", "market_market_gtc"):
            value = config.get(key)
            if value:
                return ("market", value)

        return ("unknown", None)


def parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    value = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def parse_side(value: Optional[str]) -> OrderSide:
    if not value:
        return OrderSide.BUY
    try:
        return OrderSide(value.upper())
    except ValueError:
        return OrderSide.BUY


def sum_fills(fills: Sequence[dict]) -> Optional[Decimal]:
    if not fills:
        return None
    total = Decimal("0")
    for fill in fills:
        size_value = fill.get("size") or fill.get("base_size")
        if size_value is None:
            continue
        try:
            total += Decimal(str(size_value))
        except Exception:
            continue
    return total if total > 0 else None


def average_fill_price(fills: Sequence[dict]) -> Optional[Decimal]:
    if not fills:
        return None
    total_size = Decimal("0")
    total_quote = Decimal("0")
    for fill in fills:
        size_value = fill.get("size") or fill.get("base_size")
        price_value = fill.get("price") or fill.get("unit_price") or fill.get("average_price")
        if size_value is None or price_value is None:
            continue
        try:
            size = Decimal(str(size_value))
            price = Decimal(str(price_value))
        except Exception:
            continue
        if size <= 0 or price <= 0:
            continue
        total_size += size
        total_quote += size * price
    if total_size <= 0 or total_quote <= 0:
        return None
    return total_quote / total_size


def parse_decimal(value: Any) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    try:
        decimal_value = Decimal(str(value))
    except Exception:
        return None
    return decimal_value

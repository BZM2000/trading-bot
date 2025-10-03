from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterable, Optional, Sequence

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import models


@dataclass(slots=True)
class PromptRecord:
    ts: datetime
    prompt_text: str
    response_text: str
    compact_summary_500w: Optional[str]
    sources_json: Optional[dict[str, Any]]


@dataclass(slots=True)
class PlanRecord:
    ts: datetime
    raw_text: str
    machine_json: Optional[dict[str, Any]]


@dataclass(slots=True)
class TwoHourPlanRecord(PlanRecord):
    t0_mid: Decimal


@dataclass(slots=True)
class ExecutedOrderRecord:
    order_id: str
    ts_submitted: datetime
    ts_filled: Optional[datetime]
    side: models.OrderSide
    limit_price: Decimal
    base_size: Decimal
    status: models.OrderStatus
    filled_size: Optional[Decimal]
    client_order_id: str
    end_time: datetime
    product_id: str
    stop_price: Optional[Decimal] = None
    ts_submitted_inferred: bool = False
    post_only: Optional[bool] = None


@dataclass(slots=True)
class OpenOrderRecord:
    order_id: str
    side: models.OrderSide
    limit_price: Decimal
    base_size: Decimal
    status: models.OrderStatus
    client_order_id: str
    end_time: datetime
    product_id: str
    stop_price: Optional[Decimal] = None


@dataclass(slots=True)
class PortfolioSnapshotRecord:
    ts: datetime
    balances_json: dict[str, Any]


@dataclass(slots=True)
class PriceSnapshotRecord:
    ts: datetime
    product_id: str
    best_bid: Decimal
    best_ask: Decimal
    mid: Decimal


def log_run_start(session: Session, kind: models.RunKind, *, usage_json: Optional[dict[str, Any]] = None) -> models.RunLog:
    run = models.RunLog(kind=kind, usage_json=usage_json)
    session.add(run)
    session.flush()
    return run


def log_run_finish(
    session: Session,
    run: models.RunLog,
    *,
    status: models.RunStatus = models.RunStatus.SUCCESS,
    error_text: Optional[str] = None,
    usage_json: Optional[dict[str, Any]] = None,
) -> models.RunLog:
    run.status = status
    run.finished_at = datetime.now(timezone.utc)
    if error_text:
        run.error_text = error_text
    if usage_json is not None:
        run.usage_json = usage_json
    session.add(run)
    session.flush()
    return run


def save_prompt_history(
    session: Session,
    kind: models.RunKind,
    record: PromptRecord,
) -> None:
    if kind == models.RunKind.DAILY:
        model = models.PromptHistoryDaily(
            ts=record.ts,
            prompt_text=record.prompt_text,
            response_text=record.response_text,
            compact_summary_500w=record.compact_summary_500w,
            sources_json=record.sources_json,
        )
    elif kind == models.RunKind.TWO_HOURLY:
        model = models.PromptHistory2H(
            ts=record.ts,
            prompt_text=record.prompt_text,
            response_text=record.response_text,
            compact_summary_500w=record.compact_summary_500w,
            sources_json=record.sources_json,
        )
    else:
        raise ValueError(f"Prompt history unsupported for kind={kind}")

    session.add(model)
    session.flush()


def get_recent_prompt_history(
    session: Session,
    kind: models.RunKind,
    *,
    limit: int = 7,
) -> list[Any]:
    table = {
        models.RunKind.DAILY: models.PromptHistoryDaily,
        models.RunKind.TWO_HOURLY: models.PromptHistory2H,
    }.get(kind)

    if table is None:
        raise ValueError(f"Prompt history unsupported for kind={kind}")

    statement = select(table).order_by(table.ts.desc()).limit(limit)
    return list(session.scalars(statement))


def save_daily_plan(session: Session, record: PlanRecord) -> models.DailyPlan:
    plan = models.DailyPlan(ts=record.ts, raw_text=record.raw_text, machine_json=record.machine_json)
    session.add(plan)
    session.flush()
    return plan


def save_two_hour_plan(session: Session, record: TwoHourPlanRecord) -> models.TwoHourPlan:
    plan = models.TwoHourPlan(
        ts=record.ts,
        t0_mid=record.t0_mid,
        raw_text=record.raw_text,
        machine_json=record.machine_json,
    )
    session.add(plan)
    session.flush()
    return plan


def upsert_executed_orders(session: Session, records: Sequence[ExecutedOrderRecord]) -> set[str]:
    existing_ids = {r.order_id for r in records}
    if not existing_ids:
        return set()

    existing_orders = {
        order.order_id: order
        for order in session.scalars(
            select(models.ExecutedOrder).where(models.ExecutedOrder.order_id.in_(existing_ids))
        ).all()
    }

    changed: set[str] = set()

    for record in records:
        order = existing_orders.get(record.order_id)
        if order is not None:
            prev_status = order.status
            prev_filled = order.filled_size
            prev_filled_time = order.ts_filled
            prev_post_only = getattr(order, "post_only", None)

            if not (record.ts_submitted_inferred and order.ts_submitted):
                order.ts_submitted = record.ts_submitted
            order.ts_filled = record.ts_filled
            order.side = record.side
            order.limit_price = record.limit_price
            order.base_size = record.base_size
            order.status = record.status
            order.filled_size = record.filled_size
            order.client_order_id = record.client_order_id
            order.end_time = record.end_time
            order.product_id = record.product_id
            order.stop_price = record.stop_price
            order.post_only = record.post_only

            if (
                order.status != prev_status
                or order.filled_size != prev_filled
                or order.ts_filled != prev_filled_time
                or order.stop_price != record.stop_price
                or order.post_only != prev_post_only
            ):
                changed.add(order.order_id)
        else:
            session.add(
                models.ExecutedOrder(
                    order_id=record.order_id,
                    ts_submitted=record.ts_submitted,
                    ts_filled=record.ts_filled,
                    side=record.side,
                    limit_price=record.limit_price,
                    base_size=record.base_size,
                    status=record.status,
                    filled_size=record.filled_size,
                    client_order_id=record.client_order_id,
                    end_time=record.end_time,
                    product_id=record.product_id,
                    stop_price=record.stop_price,
                    post_only=record.post_only,
                )
            )
            changed.add(record.order_id)
    session.flush()
    return changed


def replace_open_orders(session: Session, records: Sequence[OpenOrderRecord]) -> None:
    product_ids = {record.product_id for record in records}
    if product_ids:
        session.execute(delete(models.OpenOrder).where(models.OpenOrder.product_id.in_(product_ids)))
    else:
        session.execute(delete(models.OpenOrder))

    for record in records:
                session.add(
                    models.OpenOrder(
                        order_id=record.order_id,
                        side=record.side,
                        limit_price=record.limit_price,
                        base_size=record.base_size,
                        status=record.status,
                        client_order_id=record.client_order_id,
                        end_time=record.end_time,
                        product_id=record.product_id,
                        stop_price=record.stop_price,
                    )
                )
    session.flush()


def record_portfolio_snapshot(session: Session, record: PortfolioSnapshotRecord) -> models.PortfolioSnapshot:
    snapshot = models.PortfolioSnapshot(ts=record.ts, balances_json=record.balances_json)
    session.add(snapshot)
    session.flush()
    return snapshot


def record_price_snapshot(session: Session, record: PriceSnapshotRecord) -> models.PriceSnapshot:
    snapshot = models.PriceSnapshot(
        ts=record.ts,
        product_id=record.product_id,
        best_bid=record.best_bid,
        best_ask=record.best_ask,
        mid=record.mid,
    )
    session.add(snapshot)
    session.flush()
    return snapshot


def list_open_orders(session: Session, *, product_id: Optional[str] = None) -> list[models.OpenOrder]:
    statement = select(models.OpenOrder)
    if product_id:
        statement = statement.where(models.OpenOrder.product_id == product_id)
    statement = statement.order_by(models.OpenOrder.end_time.asc())
    return list(session.scalars(statement))


def latest_daily_plan(session: Session) -> Optional[models.DailyPlan]:
    statement = select(models.DailyPlan).order_by(models.DailyPlan.ts.desc()).limit(1)
    return session.scalars(statement).first()


def latest_two_hour_plan(session: Session) -> Optional[models.TwoHourPlan]:
    statement = select(models.TwoHourPlan).order_by(models.TwoHourPlan.ts.desc()).limit(1)
    return session.scalars(statement).first()


def latest_portfolio_snapshot(session: Session) -> Optional[models.PortfolioSnapshot]:
    statement = select(models.PortfolioSnapshot).order_by(models.PortfolioSnapshot.ts.desc()).limit(1)
    return session.scalars(statement).first()


def latest_price_snapshot(session: Session, product_id: str) -> Optional[models.PriceSnapshot]:
    statement = (
        select(models.PriceSnapshot)
        .where(models.PriceSnapshot.product_id == product_id)
        .order_by(models.PriceSnapshot.ts.desc())
        .limit(1)
    )
    return session.scalars(statement).first()


def executed_orders_since(
    session: Session,
    since: datetime,
    *,
    product_id: Optional[str] = None,
    limit: Optional[int] = None,
) -> list[models.ExecutedOrder]:
    statement = select(models.ExecutedOrder).where(models.ExecutedOrder.ts_submitted >= since)
    if product_id:
        statement = statement.where(models.ExecutedOrder.product_id == product_id)
    statement = statement.order_by(models.ExecutedOrder.ts_submitted.desc())
    if limit:
        statement = statement.limit(limit)
    return list(session.scalars(statement))


def recent_executed_orders(
    session: Session,
    *,
    hours: int,
    product_id: Optional[str] = None,
    limit: Optional[int] = None,
) -> list[models.ExecutedOrder]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    return executed_orders_since(session, cutoff, product_id=product_id, limit=limit)


def recent_run_logs(session: Session, limit: int = 20) -> list[models.RunLog]:
    statement = select(models.RunLog).order_by(models.RunLog.started_at.desc()).limit(limit)
    return list(session.scalars(statement))


def earliest_run_log(session: Session) -> Optional[models.RunLog]:
    statement = select(models.RunLog).order_by(models.RunLog.started_at.asc()).limit(1)
    return session.scalars(statement).first()

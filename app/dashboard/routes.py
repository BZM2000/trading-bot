from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Iterable, List

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import Settings, get_settings
from app.coinbase.client import CoinbaseClient
from app.dashboard import pnl
from app.db import crud, session_scope
from app.db.models import OrderStatus

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

templates = Jinja2Templates(directory="app/dashboard/templates")

logger = logging.getLogger(__name__)


def _resolve_settings(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    return settings or get_settings()


def _select_latest_per_order(records: Iterable[Any], *, limit: int = 20) -> List[Any]:
    """Return the newest record per order_id, sorted by event time."""

    def _key(record: Any) -> datetime:
        return (record.ts_filled or record.ts_submitted)

    by_order: dict[str, Any] = {}
    for record in records:
        order_id = getattr(record, "order_id", None)
        if not order_id:
            continue
        current = by_order.get(order_id)
        if current is None or _key(record) > _key(current):
            by_order[order_id] = record

    sorted_records = sorted(by_order.values(), key=_key, reverse=True)
    return sorted_records[:limit]


async def _load_common_context(settings: Settings) -> Dict[str, Any]:
    with session_scope(settings) as session:
        daily_plan = crud.latest_daily_plan(session)
        two_hour_plan = crud.latest_two_hour_plan(session)
        open_orders = crud.list_open_orders(session, product_id=settings.product_id)
        recent_executed = crud.recent_executed_orders(
            session,
            hours=24,
            product_id=settings.product_id,
            limit=100,
        )
        recent_executed = [
            record
            for record in recent_executed
            if record.status not in {OrderStatus.OPEN, OrderStatus.NEW}
        ]
        recent_executed = _select_latest_per_order(recent_executed, limit=20)
        run_logs = crud.recent_run_logs(session, limit=25)
        portfolio = crud.latest_portfolio_snapshot(session)
        price = crud.latest_price_snapshot(session, settings.product_id)
    pnl_summary = await _resolve_pnl_summary(settings)
    return {
        "daily_plan": daily_plan,
        "two_hour_plan": two_hour_plan,
        "open_orders": open_orders,
        "recent_executed": recent_executed,
        "run_logs": run_logs,
        "portfolio": portfolio,
        "price": price,
        "settings": settings,
        "pnl_summary": pnl_summary,
    }


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    settings = _resolve_settings(request)
    context = await _load_common_context(settings)
    context["request"] = request
    return templates.TemplateResponse("dashboard.html", context)


@router.get("/plans", response_class=HTMLResponse)
async def plans_partial(request: Request) -> HTMLResponse:
    settings = _resolve_settings(request)
    context = await _load_common_context(settings)
    context["request"] = request
    return templates.TemplateResponse("partials/plans.html", context)


@router.get("/orders", response_class=HTMLResponse)
async def orders_partial(request: Request) -> HTMLResponse:
    settings = _resolve_settings(request)
    context = await _load_common_context(settings)
    context["request"] = request
    return templates.TemplateResponse("partials/orders.html", context)


@router.get("/status", response_class=HTMLResponse)
async def status_partial(request: Request) -> HTMLResponse:
    settings = _resolve_settings(request)
    context = await _load_common_context(settings)
    context["request"] = request
    return templates.TemplateResponse("partials/runs.html", context)


async def _resolve_pnl_summary(settings: Settings) -> pnl.PNLSummary:
    try:
        async with CoinbaseClient(settings=settings) as client:
            return await pnl.calculate_pnl_summary(client, product_id=settings.product_id)
    except Exception:
        logger.exception("Failed to load PnL summary from Coinbase", extra={"product_id": settings.product_id})
        return pnl.empty_summary()

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import Settings, get_settings
from app.db import crud, session_scope

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

templates = Jinja2Templates(directory="app/dashboard/templates")


def _resolve_settings(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    return settings or get_settings()


def _load_common_context(settings: Settings) -> Dict[str, Any]:
    with session_scope(settings) as session:
        daily_plan = crud.latest_daily_plan(session)
        two_hour_plan = crud.latest_two_hour_plan(session)
        open_orders = crud.list_open_orders(session, product_id=settings.product_id)
        recent_executed = crud.recent_executed_orders(
            session,
            hours=24,
            product_id=settings.product_id,
            limit=20,
        )
        run_logs = crud.recent_run_logs(session, limit=25)
        portfolio = crud.latest_portfolio_snapshot(session)
        price = crud.latest_price_snapshot(session, settings.product_id)
    return {
        "daily_plan": daily_plan,
        "two_hour_plan": two_hour_plan,
        "open_orders": open_orders,
        "recent_executed": recent_executed,
        "run_logs": run_logs,
        "portfolio": portfolio,
        "price": price,
        "settings": settings,
    }


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    settings = _resolve_settings(request)
    context = _load_common_context(settings)
    context["request"] = request
    return templates.TemplateResponse("dashboard.html", context)


@router.get("/plans", response_class=HTMLResponse)
async def plans_partial(request: Request) -> HTMLResponse:
    settings = _resolve_settings(request)
    context = _load_common_context(settings)
    context["request"] = request
    return templates.TemplateResponse("partials/plans.html", context)


@router.get("/orders", response_class=HTMLResponse)
async def orders_partial(request: Request) -> HTMLResponse:
    settings = _resolve_settings(request)
    context = _load_common_context(settings)
    context["request"] = request
    return templates.TemplateResponse("partials/orders.html", context)


@router.get("/status", response_class=HTMLResponse)
async def status_partial(request: Request) -> HTMLResponse:
    settings = _resolve_settings(request)
    context = _load_common_context(settings)
    context["request"] = request
    return templates.TemplateResponse("partials/runs.html", context)

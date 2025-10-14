from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import APIRouter, FastAPI, Request

from app.scheduler.orchestration import get_orchestrator

router = APIRouter(prefix="/force", tags=["scheduler"])


async def plan_job(app: FastAPI) -> None:
    orchestrator = get_orchestrator(app)
    await orchestrator.run_plan()


async def order_job(app: FastAPI, *, triggered_by: str = "schedule") -> None:
    orchestrator = get_orchestrator(app)
    await orchestrator.run_order(triggered_by=triggered_by)


async def monitor_job(app: FastAPI) -> None:
    orchestrator = get_orchestrator(app)
    await orchestrator.run_monitor()


async def pnl_job(app: FastAPI) -> None:
    orchestrator = get_orchestrator(app)
    await orchestrator.run_pnl()


def register_jobs(scheduler: AsyncIOScheduler, app: FastAPI) -> None:
    scheduler.add_job(
        plan_job,
        trigger=CronTrigger(hour=0, minute=0),
        kwargs={"app": app},
        id="plan_process",
        replace_existing=True,
    )
    scheduler.add_job(
        monitor_job,
        trigger=IntervalTrigger(minutes=1),
        kwargs={"app": app},
        id="monitor_process",
        replace_existing=True,
    )
    scheduler.add_job(
        pnl_job,
        trigger=IntervalTrigger(hours=6),
        kwargs={"app": app},
        id="pnl_process",
        replace_existing=True,
    )


@router.post("/plan")
async def force_plan(request: Request) -> dict[str, str]:
    await plan_job(request.app)
    return {"status": "ok"}


@router.post("/order")
async def force_order(request: Request) -> dict[str, str]:
    await order_job(request.app, triggered_by="manual")
    return {"status": "ok"}


@router.post("/pnl")
async def force_pnl(request: Request) -> dict[str, str]:
    await pnl_job(request.app)
    return {"status": "ok"}

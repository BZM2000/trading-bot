from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import APIRouter, FastAPI, Request

from app.scheduler.orchestration import get_orchestrator

router = APIRouter(prefix="/force", tags=["scheduler"])


async def daily_job(app: FastAPI) -> None:
    orchestrator = get_orchestrator(app)
    await orchestrator.run_daily()


async def two_hourly_job(app: FastAPI, *, triggered_by: str = "schedule") -> None:
    orchestrator = get_orchestrator(app)
    await orchestrator.run_two_hourly(triggered_by=triggered_by)


async def fill_poller_job(app: FastAPI) -> None:
    orchestrator = get_orchestrator(app)
    await orchestrator.run_fill_poller()


def register_jobs(scheduler: AsyncIOScheduler, app: FastAPI) -> None:
    scheduler.add_job(
        daily_job,
        trigger=CronTrigger(hour=0, minute=0),
        kwargs={"app": app},
        id="daily_plan",
        replace_existing=True,
    )
    scheduler.add_job(
        fill_poller_job,
        trigger=IntervalTrigger(minutes=5),
        kwargs={"app": app},
        id="fill_poller",
        replace_existing=True,
    )


@router.post("/daily")
async def force_daily(request: Request) -> dict[str, str]:
    await daily_job(request.app)
    return {"status": "ok"}


@router.post("/2h")
async def force_two_hour(request: Request) -> dict[str, str]:
    await two_hourly_job(request.app, triggered_by="manual")
    return {"status": "ok"}

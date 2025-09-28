import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from apscheduler.events import EVENT_JOB_ERROR, JobExecutionEvent
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse

from app.config import Settings, get_settings
from app.dashboard.routes import router as dashboard_router
from app.logging import setup_logging
from app.scheduler.jobs import register_jobs, router as scheduler_router
from app.scheduler.orchestration import SchedulerOrchestrator


def create_scheduler(settings: Settings) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=settings.app_timezone)
    scheduler.configure(job_defaults={"max_instances": settings.scheduler_max_instances})

    if settings.scheduler_jobstore_url:
        from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

        scheduler.add_jobstore(SQLAlchemyJobStore(url=settings.scheduler_jobstore_url))

    return scheduler


def _handle_job_error(event: JobExecutionEvent) -> None:
    if event.exception:
        scheduler_logger = logging.getLogger("apscheduler.job")
        scheduler_logger.error(
            "scheduled job failed",
            extra={
                "job_id": event.job_id,
                "exception": str(event.exception),
            },
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    setup_logging(settings.log_level)


    app.state.settings = settings
    scheduler = create_scheduler(settings)
    scheduler.add_listener(_handle_job_error, EVENT_JOB_ERROR)
    app.state.scheduler = scheduler
    app.state.orchestrator = SchedulerOrchestrator(settings)
    register_jobs(scheduler, app)
    scheduler.start()

    try:
        yield
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)


app = FastAPI(lifespan=lifespan)
app.include_router(scheduler_router)
app.include_router(dashboard_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
async def root() -> RedirectResponse:
    return RedirectResponse(url="/dashboard/")


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


@app.get("/config")
async def read_config(settings: Settings = Depends(get_app_settings)) -> dict[str, str]:
    return {
        "environment": settings.environment,
        "product_id": settings.product_id,
        "timezone": settings.app_timezone,
    }

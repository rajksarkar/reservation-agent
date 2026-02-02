"""Dashboard API routes."""

from fastapi import APIRouter, Depends, Request

from reservation_agent.api.app import get_orchestrator
from reservation_agent.db.repository import Repository

router = APIRouter()


def get_repository(request: Request) -> Repository:
    """Dependency to get repository from app state."""
    return request.app.state.repository


@router.get("/dashboard")
async def get_dashboard(
    request: Request,
    repository: Repository = Depends(get_repository),
):
    """Get dashboard data."""
    stats = await repository.get_dashboard_stats()

    orchestrator = get_orchestrator()
    jobs = []
    if orchestrator and orchestrator.scheduler:
        jobs = orchestrator.scheduler.get_jobs()

    return {
        "stats": stats,
        "jobs": jobs,
    }


@router.get("/dashboard/stats")
async def get_stats(
    repository: Repository = Depends(get_repository),
):
    """Get dashboard statistics."""
    return await repository.get_dashboard_stats()


@router.get("/dashboard/jobs")
async def get_jobs():
    """Get scheduled jobs."""
    orchestrator = get_orchestrator()
    if not orchestrator or not orchestrator.scheduler:
        return {"jobs": []}

    return {"jobs": orchestrator.scheduler.get_jobs()}


@router.get("/dashboard/activity")
async def get_activity(
    repository: Repository = Depends(get_repository),
    limit: int = 50,
    category: str | None = None,
):
    """Get activity log."""
    logs = await repository.get_activity_log(category=category, limit=limit)
    return {
        "activity": [
            {
                "id": log.id,
                "level": log.level,
                "category": log.category,
                "message": log.message,
                "created_at": log.created_at.isoformat(),
            }
            for log in logs
        ]
    }

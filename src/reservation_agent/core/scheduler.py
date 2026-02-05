"""APScheduler-based job scheduling."""

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Coroutine

from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from reservation_agent.core.config import SchedulerConfig
from reservation_agent.utils.logging import get_logger

logger = get_logger(__name__)


class JobScheduler:
    """Manages scheduled jobs for reservation monitoring."""

    def __init__(
        self,
        config: SchedulerConfig,
        database_url: str,
        base_dir: Path | None = None,
    ):
        self.config = config
        self.base_dir = base_dir or Path.cwd()

        # MemoryJobStore avoids pickle errors with async callbacks (Orchestrator
        # methods can't be serialized). Jobs are recreated from config on start.
        jobstores = {
            "default": MemoryJobStore(),
        }
        executors = {
            "default": AsyncIOExecutor(),
        }
        job_defaults = {
            "coalesce": True,  # Combine multiple missed runs
            "max_instances": 3,  # Allow up to 3 concurrent instances per job
            "misfire_grace_time": 60,  # Allow 60s grace for misfires
        }

        self.scheduler = AsyncIOScheduler(
            jobstores=jobstores,
            executors=executors,
            job_defaults=job_defaults,
            timezone="America/New_York",
        )

        self._running = False

    def start(self) -> None:
        """Start the scheduler."""
        if not self._running:
            self.scheduler.start()
            self._running = True
            logger.info("scheduler_started")

    def shutdown(self, wait: bool = True) -> None:
        """Shutdown the scheduler."""
        if self._running:
            self.scheduler.shutdown(wait=wait)
            self._running = False
            logger.info("scheduler_stopped")

    def schedule_release_snipe(
        self,
        job_id: str,
        target_date: str,
        release_time: str,
        release_days_ahead: int,
        callback: Callable[..., Coroutine[Any, Any, Any]],
        **kwargs,
    ) -> str:
        """Schedule a job to snipe reservations when they're released.

        Args:
            job_id: Unique job identifier
            target_date: The date we want to book (YYYY-MM-DD)
            release_time: Time of day reservations are released (HH:MM)
            release_days_ahead: How many days before target date reservations open
            callback: Async function to call at release time
            **kwargs: Arguments to pass to callback

        Returns:
            The job ID
        """
        # Calculate release date
        target = datetime.strptime(target_date, "%Y-%m-%d")
        release_date = target - timedelta(days=release_days_ahead)

        # Parse release time
        release_hour, release_minute = map(int, release_time.split(":"))

        # Combine date and time, wake up early
        release_datetime = release_date.replace(
            hour=release_hour, minute=release_minute, second=0, microsecond=0
        )
        wake_datetime = release_datetime - timedelta(seconds=self.config.snipe_wake_before)

        # Don't schedule if already past
        if wake_datetime <= datetime.now():
            logger.warning(
                "release_already_passed",
                job_id=job_id,
                release_datetime=release_datetime.isoformat(),
            )
            return job_id

        # Schedule the job
        self.scheduler.add_job(
            callback,
            trigger=DateTrigger(run_date=wake_datetime),
            id=job_id,
            name=f"release_snipe_{job_id}",
            replace_existing=True,
            kwargs=kwargs,
        )

        logger.info(
            "scheduled_release_snipe",
            job_id=job_id,
            target_date=target_date,
            release_datetime=release_datetime.isoformat(),
            wake_datetime=wake_datetime.isoformat(),
        )

        return job_id

    def schedule_cancellation_monitor(
        self,
        job_id: str,
        callback: Callable[..., Coroutine[Any, Any, Any]],
        interval_seconds: int | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        **kwargs,
    ) -> str:
        """Schedule recurring cancellation monitoring.

        Args:
            job_id: Unique job identifier
            callback: Async function to call on each check
            interval_seconds: Seconds between checks (default from config)
            start_time: When to start monitoring (default: now)
            end_time: When to stop monitoring (optional)
            **kwargs: Arguments to pass to callback

        Returns:
            The job ID
        """
        interval = interval_seconds or self.config.cancellation_poll_interval
        start = start_time or datetime.now()

        trigger_kwargs = {"seconds": interval}
        if end_time:
            trigger_kwargs["end_date"] = end_time

        self.scheduler.add_job(
            callback,
            trigger=IntervalTrigger(**trigger_kwargs),
            id=job_id,
            name=f"cancellation_monitor_{job_id}",
            replace_existing=True,
            next_run_time=start,
            kwargs=kwargs,
        )

        logger.info(
            "scheduled_cancellation_monitor",
            job_id=job_id,
            interval_seconds=interval,
            start_time=start.isoformat(),
            end_time=end_time.isoformat() if end_time else None,
        )

        return job_id

    def schedule_daily_check(
        self,
        job_id: str,
        callback: Callable[..., Coroutine[Any, Any, Any]],
        hour: int = 8,
        minute: int = 0,
        **kwargs,
    ) -> str:
        """Schedule a daily job at a specific time.

        Args:
            job_id: Unique job identifier
            callback: Async function to call daily
            hour: Hour of day (0-23)
            minute: Minute of hour (0-59)
            **kwargs: Arguments to pass to callback

        Returns:
            The job ID
        """
        self.scheduler.add_job(
            callback,
            trigger=CronTrigger(hour=hour, minute=minute),
            id=job_id,
            name=f"daily_{job_id}",
            replace_existing=True,
            kwargs=kwargs,
        )

        logger.info(
            "scheduled_daily_check",
            job_id=job_id,
            time=f"{hour:02d}:{minute:02d}",
        )

        return job_id

    def remove_job(self, job_id: str) -> bool:
        """Remove a scheduled job."""
        try:
            self.scheduler.remove_job(job_id)
            logger.info("removed_job", job_id=job_id)
            return True
        except Exception:
            return False

    def pause_job(self, job_id: str) -> bool:
        """Pause a scheduled job."""
        try:
            self.scheduler.pause_job(job_id)
            logger.info("paused_job", job_id=job_id)
            return True
        except Exception:
            return False

    def resume_job(self, job_id: str) -> bool:
        """Resume a paused job."""
        try:
            self.scheduler.resume_job(job_id)
            logger.info("resumed_job", job_id=job_id)
            return True
        except Exception:
            return False

    def get_jobs(self) -> list[dict]:
        """Get all scheduled jobs."""
        jobs = []
        for job in self.scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                "trigger": str(job.trigger),
            })
        return jobs

    def get_job(self, job_id: str) -> dict | None:
        """Get a specific job by ID."""
        job = self.scheduler.get_job(job_id)
        if job:
            return {
                "id": job.id,
                "name": job.name,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                "trigger": str(job.trigger),
            }
        return None


class RapidPoller:
    """Handles rapid polling during release window."""

    def __init__(
        self,
        interval_ms: float = 500,
        duration_seconds: int = 10,
    ):
        self.interval = interval_ms / 1000
        self.duration = duration_seconds
        self._stop_event = asyncio.Event()

    async def poll(
        self,
        callback: Callable[..., Coroutine[Any, Any, bool]],
        **kwargs,
    ) -> bool:
        """Rapidly poll until success or timeout.

        Args:
            callback: Async function that returns True on success
            **kwargs: Arguments to pass to callback

        Returns:
            True if callback succeeded, False if timed out
        """
        self._stop_event.clear()
        end_time = asyncio.get_event_loop().time() + self.duration

        logger.info(
            "starting_rapid_poll",
            interval_ms=self.interval * 1000,
            duration_seconds=self.duration,
        )

        attempt = 0
        while asyncio.get_event_loop().time() < end_time:
            if self._stop_event.is_set():
                break

            attempt += 1
            try:
                success = await callback(**kwargs)
                if success:
                    logger.info("rapid_poll_success", attempt=attempt)
                    return True
            except Exception as e:
                logger.warning("rapid_poll_error", attempt=attempt, error=str(e))

            await asyncio.sleep(self.interval)

        logger.info("rapid_poll_timeout", attempts=attempt)
        return False

    def stop(self) -> None:
        """Stop the rapid polling."""
        self._stop_event.set()

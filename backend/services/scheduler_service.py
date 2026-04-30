"""
Scheduler service for managing cron-like scheduled syncs.
Uses APScheduler with in-memory job storage (jobs loaded from config.yaml on startup).
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)


class SchedulerService:
    """Manages scheduled sync jobs using APScheduler with in-memory storage."""

    def __init__(self):
        # Use in-memory job store - jobs are loaded from config.yaml on startup
        jobstores = {"default": MemoryJobStore()}

        self.scheduler = AsyncIOScheduler(
            jobstores=jobstores,
            timezone=UTC,
            job_defaults={
                "coalesce": True,  # Combine missed runs into one
                "max_instances": 1,  # Only one instance of each job at a time
            },
        )

        # Track job execution callback
        self._on_job_executed: Callable | None = None
        self._on_job_error: Callable | None = None

    def start(self):
        """Start the scheduler."""
        if not self.scheduler.running:
            self.scheduler.add_listener(self._job_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)
            self.scheduler.start()

    def shutdown(self):
        """Shutdown the scheduler gracefully."""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=True)

    def _job_listener(self, event):
        """Handle job execution events."""
        if event.exception:
            if self._on_job_error:
                self._on_job_error(event.job_id, str(event.exception))
        else:
            if self._on_job_executed:
                self._on_job_executed(event.job_id, event.retval)

    def add_sync_job(
        self,
        job_id: str,
        cron_expression: str,
        sync_func: Callable,
        kindle_device: str | None = None,
        dry_run: bool = False,
    ) -> dict:
        """
        Add a scheduled sync job.

        Args:
            job_id: Unique identifier for the job
            cron_expression: Cron expression (e.g., "0 2 * * *" for 2am daily)
            sync_func: Async function to call when job triggers
            kindle_device: Target Kindle device ID
            dry_run: Whether to run in dry-run mode
        """
        # Parse cron expression
        try:
            trigger = CronTrigger.from_crontab(cron_expression)
        except ValueError as e:
            raise ValueError(f"Invalid cron expression: {e}")

        # Remove existing job if it exists
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)

        # Add the job
        job = self.scheduler.add_job(
            sync_func,
            trigger=trigger,
            id=job_id,
            name=f"Scheduled sync: {job_id}",
            kwargs={
                "kindle_device": kindle_device,
                "dry_run": dry_run,
                "trigger_type": "scheduled",
            },
            replace_existing=True,
        )

        return {
            "job_id": job.id,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
        }

    def add_rss_sync_job(
        self,
        job_id: str,
        cron_expression: str,
        sync_func: Callable,
    ) -> None:
        """
        Add a scheduled RSS sync job.

        Args:
            job_id: Unique identifier for the job
            cron_expression: Cron expression (e.g., "0 2 * * *" for 2am daily)
            sync_func: Async function to call when job triggers (called with no arguments)

        On invalid cron expression: logs ERROR and returns None (does not raise).
        """
        # Parse cron expression
        try:
            trigger = CronTrigger.from_crontab(cron_expression)
        except ValueError as e:
            logger.error(f"Invalid cron expression for RSS sync job '{job_id}': {e}")
            return None

        # Remove existing job if it exists
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)

        # Add the job (no kwargs passed to sync_func)
        self.scheduler.add_job(
            sync_func,
            trigger=trigger,
            id=job_id,
            name=f"RSS sync: {job_id}",
            replace_existing=True,
        )

        logger.info(f"RSS sync job '{job_id}' registered with cron: {cron_expression}")

    def add_rss_cleanup_job(
        self,
        job_id: str,
        cron_expression: str,
        cleanup_func: Callable,
    ) -> None:
        """
        Add a scheduled RSS cleanup job.

        Args:
            job_id: Unique identifier for the job
            cron_expression: Cron expression (e.g., "0 2 * * *" for 2am daily)
            cleanup_func: Async function to call when job triggers (called with no arguments)

        On invalid cron expression: logs ERROR and returns None (does not raise).
        """
        # Parse cron expression
        try:
            trigger = CronTrigger.from_crontab(cron_expression)
        except ValueError as e:
            logger.error(f"Invalid cron expression for RSS cleanup job '{job_id}': {e}")
            return None

        # Remove existing job if it exists
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)

        # Add the job (no kwargs passed to cleanup_func)
        self.scheduler.add_job(
            cleanup_func,
            trigger=trigger,
            id=job_id,
            name=f"RSS cleanup: {job_id}",
            replace_existing=True,
        )

        logger.info(f"RSS cleanup job '{job_id}' registered with cron: {cron_expression}")

    def remove_job(self, job_id: str) -> bool:
        """Remove a scheduled job."""
        job = self.scheduler.get_job(job_id)
        if job:
            self.scheduler.remove_job(job_id)
            return True
        return False

    def pause_job(self, job_id: str) -> bool:
        """Pause a scheduled job."""
        job = self.scheduler.get_job(job_id)
        if job:
            self.scheduler.pause_job(job_id)
            return True
        return False

    def resume_job(self, job_id: str) -> bool:
        """Resume a paused job."""
        job = self.scheduler.get_job(job_id)
        if job:
            self.scheduler.resume_job(job_id)
            return True
        return False

    def get_job(self, job_id: str) -> dict | None:
        """Get job details."""
        job = self.scheduler.get_job(job_id)
        if not job:
            return None

        return {
            "job_id": job.id,
            "name": job.name,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            "pending": job.pending,
        }

    def get_all_jobs(self) -> list[dict]:
        """Get all scheduled jobs."""
        jobs = []
        for job in self.scheduler.get_jobs():
            jobs.append(
                {
                    "job_id": job.id,
                    "name": job.name,
                    "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                    "pending": job.pending,
                }
            )
        return jobs

    def get_next_run(self) -> datetime | None:
        """Get the next scheduled run time across all jobs."""
        next_runs = []
        for job in self.scheduler.get_jobs():
            if job.next_run_time:
                next_runs.append(job.next_run_time)

        return min(next_runs) if next_runs else None

    def set_callbacks(
        self,
        on_executed: Callable | None = None,
        on_error: Callable | None = None,
    ):
        """Set callbacks for job execution events."""
        self._on_job_executed = on_executed
        self._on_job_error = on_error

    def load_schedules_from_config(self, sync_func: Callable) -> int:
        """
        Load all enabled schedules from config.yaml and register them as jobs.

        Args:
            sync_func: The async function to call when a scheduled job triggers.

        Returns:
            Number of schedules successfully loaded.
        """
        from backend.config import get_schedules

        schedules = get_schedules()
        loaded = 0

        for schedule in schedules:
            if not schedule.get("enabled", True):
                logger.debug(f"Skipping disabled schedule: {schedule.get('name', schedule.get('id'))}")
                continue

            schedule_id = schedule.get("id")
            if not schedule_id:
                logger.warning(f"Skipping schedule without ID: {schedule}")
                continue

            try:
                self.add_sync_job(
                    job_id=f"schedule_{schedule_id}",
                    cron_expression=schedule["cron_expression"],
                    sync_func=sync_func,
                    kindle_device=schedule.get("kindle_device"),
                    dry_run=schedule.get("dry_run", False),
                )
                loaded += 1
                logger.info(f"Loaded schedule: {schedule.get('name', schedule_id)} ({schedule['cron_expression']})")
            except (ValueError, KeyError) as e:
                logger.warning(f"Failed to load schedule {schedule_id}: {e}")

        return loaded

    @staticmethod
    def get_next_run_time(cron_expression: str) -> datetime | None:
        """
        Calculate the next run time for a cron expression.

        Args:
            cron_expression: Standard 5-field cron expression (e.g., "0 2 * * *")

        Returns:
            Next run time as datetime, or None if expression is invalid.
        """
        try:
            trigger = CronTrigger.from_crontab(cron_expression)
            return trigger.get_next_fire_time(None, datetime.now(UTC))
        except ValueError:
            return None


# Global scheduler instance
scheduler = SchedulerService()

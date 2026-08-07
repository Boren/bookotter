"""
Scheduler service for background jobs (RSS sync, automatic E-reader sync).
Uses APScheduler with in-memory job storage; jobs are registered at startup
and re-registered when their config sections change.
"""

import logging
from collections.abc import Callable
from datetime import UTC

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

    def set_callbacks(
        self,
        on_executed: Callable | None = None,
        on_error: Callable | None = None,
    ):
        """Set callbacks for job execution events."""
        self._on_job_executed = on_executed
        self._on_job_error = on_error


# Global scheduler instance
scheduler = SchedulerService()

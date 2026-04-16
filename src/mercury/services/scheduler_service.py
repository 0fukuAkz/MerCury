"""Scheduler service for scheduled email sending using APScheduler."""

import logging
import asyncio
from typing import Optional, Dict, Any, List, Callable
from datetime import datetime, UTC
from dataclasses import dataclass, field
from enum import Enum

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR, JobEvent

logger = logging.getLogger(__name__)


class ScheduleType(str, Enum):
    """Type of schedule."""
    ONCE = "once"  # One-time scheduled send
    RECURRING = "recurring"  # Recurring schedule (cron)
    INTERVAL = "interval"  # Fixed interval


@dataclass
class ScheduledJob:
    """Scheduled job record."""
    id: str
    name: str
    schedule_type: ScheduleType
    scheduled_at: datetime
    campaign_id: Optional[str] = None
    cron_expression: Optional[str] = None
    interval_seconds: Optional[int] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    run_count: int = 0
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'name': self.name,
            'schedule_type': self.schedule_type.value,
            'scheduled_at': self.scheduled_at.isoformat() if self.scheduled_at else None,
            'campaign_id': self.campaign_id,
            'cron_expression': self.cron_expression,
            'interval_seconds': self.interval_seconds,
            'created_at': self.created_at.isoformat(),
            'last_run': self.last_run.isoformat() if self.last_run else None,
            'next_run': self.next_run.isoformat() if self.next_run else None,
            'run_count': self.run_count,
            'enabled': self.enabled
        }


class SchedulerService:
    """
    Service for scheduling email campaigns.
    
    Features:
    - One-time scheduled sends
    - Recurring campaigns (cron)
    - Interval-based sending
    - Job management (pause, resume, cancel)
    """
    
    def __init__(self, use_async: bool = True):
        """
        Initialize scheduler service.
        
        Args:
            use_async: Use async scheduler (for async applications)
        """
        self.use_async = use_async
        self._jobs: Dict[str, ScheduledJob] = {}
        self._callbacks: Dict[str, Callable] = {}
        
        # Configure job stores
        jobstores = {
            'default': MemoryJobStore()
        }
        
        # Create appropriate scheduler
        if use_async:
            self._scheduler = AsyncIOScheduler(jobstores=jobstores)
        else:
            self._scheduler = BackgroundScheduler(jobstores=jobstores)
        
        # Add event listeners
        self._scheduler.add_listener(self._on_job_executed, EVENT_JOB_EXECUTED)
        self._scheduler.add_listener(self._on_job_error, EVENT_JOB_ERROR)
    
    def _on_job_executed(self, event: JobEvent) -> None:
        """Handle job execution event."""
        job_id = event.job_id
        
        if job_id in self._jobs:
            job = self._jobs[job_id]
            job.last_run = datetime.now(UTC)
            job.run_count += 1
            
            # Update next run time
            scheduler_job = self._scheduler.get_job(job_id)
            if scheduler_job and scheduler_job.next_run_time:
                job.next_run = scheduler_job.next_run_time
            
            logger.info(f"Job executed: {job.name} (run #{job.run_count})")
    
    def _on_job_error(self, event: JobEvent) -> None:
        """Handle job error event."""
        job_id = event.job_id
        logger.error(f"Job error: {job_id} - {event.exception}")
    
    def start(self) -> None:
        """Start the scheduler."""
        if not self._scheduler.running:
            self._scheduler.start()
            logger.info("Scheduler started")
    
    def stop(self, wait: bool = True) -> None:
        """Stop the scheduler."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=wait)
            logger.info("Scheduler stopped")
    
    def schedule_once(
        self,
        job_id: str,
        name: str,
        run_at: datetime,
        callback: Callable,
        campaign_id: Optional[str] = None,
        **kwargs
    ) -> ScheduledJob:
        """
        Schedule a one-time job.
        
        Args:
            job_id: Unique job identifier
            name: Job name
            run_at: When to run the job
            callback: Function to call (async or sync)
            campaign_id: Associated campaign ID
            **kwargs: Additional arguments to pass to callback
            
        Returns:
            ScheduledJob record
        """
        job = ScheduledJob(
            id=job_id,
            name=name,
            schedule_type=ScheduleType.ONCE,
            scheduled_at=run_at,
            campaign_id=campaign_id,
            next_run=run_at,
            metadata=kwargs
        )
        
        self._jobs[job_id] = job
        self._callbacks[job_id] = callback
        
        trigger = DateTrigger(run_date=run_at)
        
        self._scheduler.add_job(
            self._execute_job,
            trigger=trigger,
            id=job_id,
            name=name,
            args=[job_id],
            replace_existing=True
        )
        
        logger.info(f"Scheduled one-time job: {name} at {run_at}")
        
        return job
    
    def schedule_recurring(
        self,
        job_id: str,
        name: str,
        cron_expression: str,
        callback: Callable,
        campaign_id: Optional[str] = None,
        **kwargs
    ) -> ScheduledJob:
        """
        Schedule a recurring job using cron expression.
        
        Args:
            job_id: Unique job identifier
            name: Job name
            cron_expression: Cron expression (e.g., "0 9 * * MON-FRI")
            callback: Function to call
            campaign_id: Associated campaign ID
            **kwargs: Additional arguments
            
        Returns:
            ScheduledJob record
        """
        job = ScheduledJob(
            id=job_id,
            name=name,
            schedule_type=ScheduleType.RECURRING,
            scheduled_at=datetime.now(UTC),
            campaign_id=campaign_id,
            cron_expression=cron_expression,
            metadata=kwargs
        )
        
        self._jobs[job_id] = job
        self._callbacks[job_id] = callback
        
        # Parse cron expression
        parts = cron_expression.split()
        trigger = CronTrigger(
            minute=parts[0] if len(parts) > 0 else '*',
            hour=parts[1] if len(parts) > 1 else '*',
            day=parts[2] if len(parts) > 2 else '*',
            month=parts[3] if len(parts) > 3 else '*',
            day_of_week=parts[4] if len(parts) > 4 else '*'
        )
        
        self._scheduler.add_job(
            self._execute_job,
            trigger=trigger,
            id=job_id,
            name=name,
            args=[job_id],
            replace_existing=True
        )
        
        # Get next run time
        scheduler_job = self._scheduler.get_job(job_id)
        if scheduler_job and scheduler_job.next_run_time:
            job.next_run = scheduler_job.next_run_time
        
        logger.info(f"Scheduled recurring job: {name} with cron '{cron_expression}'")
        
        return job
    
    def schedule_interval(
        self,
        job_id: str,
        name: str,
        interval_seconds: int,
        callback: Callable,
        campaign_id: Optional[str] = None,
        start_immediately: bool = False,
        **kwargs
    ) -> ScheduledJob:
        """
        Schedule a job to run at fixed intervals.
        
        Args:
            job_id: Unique job identifier
            name: Job name
            interval_seconds: Seconds between runs
            callback: Function to call
            campaign_id: Associated campaign ID
            start_immediately: Run immediately on start
            **kwargs: Additional arguments
            
        Returns:
            ScheduledJob record
        """
        job = ScheduledJob(
            id=job_id,
            name=name,
            schedule_type=ScheduleType.INTERVAL,
            scheduled_at=datetime.now(UTC),
            campaign_id=campaign_id,
            interval_seconds=interval_seconds,
            metadata=kwargs
        )
        
        self._jobs[job_id] = job
        self._callbacks[job_id] = callback
        
        trigger = IntervalTrigger(seconds=interval_seconds)
        
        self._scheduler.add_job(
            self._execute_job,
            trigger=trigger,
            id=job_id,
            name=name,
            args=[job_id],
            replace_existing=True,
            next_run_time=datetime.now(UTC) if start_immediately else None
        )
        
        # Get next run time
        scheduler_job = self._scheduler.get_job(job_id)
        if scheduler_job and scheduler_job.next_run_time:
            job.next_run = scheduler_job.next_run_time
        
        logger.info(f"Scheduled interval job: {name} every {interval_seconds}s")
        
        return job
    
    def _execute_job(self, job_id: str) -> None:
        """Execute a scheduled job."""
        if job_id not in self._callbacks:
            logger.error(f"No callback registered for job: {job_id}")
            return
        
        callback = self._callbacks[job_id]
        job = self._jobs.get(job_id)
        
        logger.debug(f"Executing job: {job.name if job else job_id}")
        
        try:
            if asyncio.iscoroutinefunction(callback):
                # Run async callback
                if self.use_async:
                    asyncio.create_task(callback(**job.metadata if job else {}))
                else:
                    from ..web.extensions import run_async
                    run_async(callback(**job.metadata if job else {}))
            else:
                # Run sync callback
                callback(**job.metadata if job else {})
                
        except Exception as e:
            logger.error(f"Job execution failed: {job_id} - {e}")
            raise
    
    def cancel_job(self, job_id: str) -> bool:
        """Cancel a scheduled job."""
        if job_id in self._jobs:
            self._scheduler.remove_job(job_id)
            del self._jobs[job_id]
            if job_id in self._callbacks:
                del self._callbacks[job_id]
            logger.info(f"Cancelled job: {job_id}")
            return True
        return False
    
    def pause_job(self, job_id: str) -> bool:
        """Pause a scheduled job."""
        if job_id in self._jobs:
            self._scheduler.pause_job(job_id)
            self._jobs[job_id].enabled = False
            logger.info(f"Paused job: {job_id}")
            return True
        return False
    
    def resume_job(self, job_id: str) -> bool:
        """Resume a paused job."""
        if job_id in self._jobs:
            self._scheduler.resume_job(job_id)
            self._jobs[job_id].enabled = True
            logger.info(f"Resumed job: {job_id}")
            return True
        return False
    
    def reschedule_job(self, job_id: str, new_time: datetime) -> bool:
        """Reschedule a one-time job."""
        if job_id in self._jobs:
            job = self._jobs[job_id]
            if job.schedule_type != ScheduleType.ONCE:
                logger.warning(f"Can only reschedule one-time jobs: {job_id}")
                return False
            
            self._scheduler.reschedule_job(
                job_id,
                trigger=DateTrigger(run_date=new_time)
            )
            
            job.scheduled_at = new_time
            job.next_run = new_time
            
            logger.info(f"Rescheduled job {job_id} to {new_time}")
            return True
        return False
    
    def get_job(self, job_id: str) -> Optional[ScheduledJob]:
        """Get job by ID."""
        return self._jobs.get(job_id)
    
    def get_all_jobs(self) -> List[ScheduledJob]:
        """Get all scheduled jobs."""
        return list(self._jobs.values())
    
    def get_pending_jobs(self) -> List[ScheduledJob]:
        """Get jobs that haven't run yet."""
        return [j for j in self._jobs.values() if j.run_count == 0]
    
    def get_jobs_by_campaign(self, campaign_id: str) -> List[ScheduledJob]:
        """Get jobs for a specific campaign."""
        return [j for j in self._jobs.values() if j.campaign_id == campaign_id]


# Convenience function for scheduling campaigns

def schedule_campaign(
    scheduler: SchedulerService,
    campaign_id: str,
    campaign_name: str,
    send_time: datetime,
    campaign_callback: Callable
) -> ScheduledJob:
    """
    Schedule a campaign to run at a specific time.
    
    Args:
        scheduler: Scheduler service instance
        campaign_id: Campaign ID
        campaign_name: Campaign name
        send_time: When to send
        campaign_callback: Function to execute the campaign
        
    Returns:
        ScheduledJob record
    """
    job_id = f"campaign_{campaign_id}"
    
    return scheduler.schedule_once(
        job_id=job_id,
        name=f"Campaign: {campaign_name}",
        run_at=send_time,
        callback=campaign_callback,
        campaign_id=campaign_id
    )


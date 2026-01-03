
import pytest
import asyncio
from datetime import datetime, UTC, timedelta
from unittest.mock import MagicMock, AsyncMock, patch
from mercury.services.scheduler_service import SchedulerService, ScheduleType, schedule_campaign

@pytest.fixture
def scheduler_service():
    """Create SchedulerService with mocked APScheduler."""
    with patch('mercury.services.scheduler_service.AsyncIOScheduler') as MockScheduler:
        service = SchedulerService(use_async=True)
        # Mock the internal scheduler instance
        service._scheduler = MockScheduler.return_value
        service._scheduler.running = False
        yield service

@pytest.mark.asyncio
class TestSchedulerServiceExtended:
    """Extended tests for SchedulerService."""

    async def test_schedule_once(self, scheduler_service):
        """Test scheduling a one-time job."""
        callback = AsyncMock()
        run_at = datetime.now(UTC) + timedelta(minutes=5)
        
        job = scheduler_service.schedule_once(
            job_id="job1",
            name="test job",
            run_at=run_at,
            callback=callback,
            campaign_id="c1",
            meta="data"
        )
        
        assert job.id == "job1"
        assert job.schedule_type == ScheduleType.ONCE
        assert job.metadata == {"meta": "data"}
        
        # Verify APScheduler add_job called
        scheduler_service._scheduler.add_job.assert_called_once()
        args, kwargs = scheduler_service._scheduler.add_job.call_args
        assert kwargs['id'] == "job1"
        assert kwargs['trigger'].run_date == run_at

    async def test_schedule_recurring(self, scheduler_service):
        """Test scheduling a recurring job."""
        callback = AsyncMock()
        cron = "0 9 * * *"
        
        job = scheduler_service.schedule_recurring(
            job_id="job2",
            name="cron job",
            cron_expression=cron,
            callback=callback
        )
        
        assert job.schedule_type == ScheduleType.RECURRING
        assert job.cron_expression == cron
        
        scheduler_service._scheduler.add_job.assert_called_once()

    async def test_schedule_interval(self, scheduler_service):
        """Test scheduling an interval job."""
        callback = AsyncMock()
        
        job = scheduler_service.schedule_interval(
            job_id="job3",
            name="interval job",
            interval_seconds=60,
            callback=callback,
            start_immediately=True
        )
        
        assert job.schedule_type == ScheduleType.INTERVAL
        assert job.interval_seconds == 60
        
        scheduler_service._scheduler.add_job.assert_called_once()
        _, kwargs = scheduler_service._scheduler.add_job.call_args
        assert kwargs['next_run_time'] is not None

    async def test_execute_job_async(self, scheduler_service):
        """Test executing an async job."""
        callback = AsyncMock()
        scheduler_service._callbacks["job1"] = callback
        scheduler_service._jobs["job1"] = MagicMock(name="job1", metadata={"key": "value"})
        
        # Test execution
        scheduler_service._execute_job("job1")
        
        # Yield to allow ensure_future/create_task to run
        await asyncio.sleep(0)
        
        callback.assert_called_once_with(key="value")

    def test_execute_job_sync(self, scheduler_service):
        """Test executing a sync job."""
        callback = MagicMock()
        scheduler_service._callbacks["job1"] = callback
        scheduler_service._jobs["job1"] = MagicMock(name="job1", metadata={"key": "value"})
        
        scheduler_service._execute_job("job1")
        
        callback.assert_called_once_with(key="value")

    def test_job_management(self, scheduler_service):
        """Test cancelling, pausing, resuming jobs."""
        # Setup job
        job_id = "job1"
        scheduler_service._jobs[job_id] = MagicMock(enabled=True)
        scheduler_service._callbacks[job_id] = lambda: None
        
        # Pause
        assert scheduler_service.pause_job(job_id) is True
        scheduler_service._scheduler.pause_job.assert_called_with(job_id)
        assert scheduler_service._jobs[job_id].enabled is False
        
        # Resume
        assert scheduler_service.resume_job(job_id) is True
        scheduler_service._scheduler.resume_job.assert_called_with(job_id)
        assert scheduler_service._jobs[job_id].enabled is True
        
        # Cancel
        assert scheduler_service.cancel_job(job_id) is True
        scheduler_service._scheduler.remove_job.assert_called_with(job_id)
        assert job_id not in scheduler_service._jobs

    def test_reschedule_job(self, scheduler_service):
        """Test rescheduling a job."""
        job_id = "job1"
        # Create full object because type check
        from mercury.services.scheduler_service import ScheduledJob
        
        job = ScheduledJob(
            id=job_id, name="test", schedule_type=ScheduleType.ONCE, 
            scheduled_at=datetime.now(UTC)
        )
        scheduler_service._jobs[job_id] = job
        
        new_time = datetime.now(UTC) + timedelta(hours=1)
        assert scheduler_service.reschedule_job(job_id, new_time) is True
        
        scheduler_service._scheduler.reschedule_job.assert_called_once()
        assert job.scheduled_at == new_time
        
        # Test rescheduling non-ONCE job
        job.schedule_type = ScheduleType.RECURRING
        assert scheduler_service.reschedule_job(job_id, new_time) is False

    def test_getters(self, scheduler_service):
        """Test job retrieval methods."""
        from mercury.services.scheduler_service import ScheduledJob
        
        j1 = ScheduledJob(id="1", name="j1", schedule_type=ScheduleType.ONCE, scheduled_at=datetime.now(UTC), campaign_id="c1", run_count=0)
        j2 = ScheduledJob(id="2", name="j2", schedule_type=ScheduleType.ONCE, scheduled_at=datetime.now(UTC), campaign_id="c2", run_count=1)
        
        scheduler_service._jobs = {"1": j1, "2": j2}
        
        assert scheduler_service.get_job("1") == j1
        assert len(scheduler_service.get_all_jobs()) == 2
        assert len(scheduler_service.get_pending_jobs()) == 1  # j1
        assert scheduler_service.get_pending_jobs()[0].id == "1"
        assert len(scheduler_service.get_jobs_by_campaign("c1")) == 1

    def test_schedule_campaign_convenience(self, scheduler_service):
        """Test schedule_campaign helper."""
        scheduler_service.schedule_once = MagicMock()
        
        dt = datetime.now(UTC)
        cb = MagicMock()
        
        schedule_campaign(scheduler_service, "c1", "Name", dt, cb)
        
        scheduler_service.schedule_once.assert_called_once()
        _, kwargs = scheduler_service.schedule_once.call_args
        assert kwargs['job_id'] == "campaign_c1"
        assert kwargs['run_at'] == dt

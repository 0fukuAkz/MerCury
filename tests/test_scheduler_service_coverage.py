"""Tests for scheduler_service.py coverage."""

import pytest
import asyncio
from datetime import datetime, timedelta, UTC
from unittest.mock import MagicMock
from mercury.services.scheduler_service import SchedulerService, ScheduleType, ScheduledJob

@pytest.fixture
async def scheduler():
    s = SchedulerService(use_async=True)
    s.start()
    yield s
    s.stop()

@pytest.mark.asyncio
async def test_scheduler_job_to_dict():
    job = ScheduledJob(
        id="j1", name="Job 1", schedule_type=ScheduleType.ONCE,
        scheduled_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    d = job.to_dict()
    assert d['id'] == "j1"
    assert d['schedule_type'] == "once"

@pytest.mark.asyncio
async def test_scheduler_schedule_once(scheduler):
    run_at = datetime.now(UTC) + timedelta(seconds=1)
    callback = MagicMock()
    job = scheduler.schedule_once("once1", "Once Job", run_at, callback)
    
    assert job.id == "once1"
    assert scheduler.get_job("once1") == job
    assert len(scheduler.get_all_jobs()) == 1

@pytest.mark.asyncio
async def test_scheduler_schedule_recurring(scheduler):
    # cron: every minute
    callback = MagicMock()
    job = scheduler.schedule_recurring("rec1", "Rec Job", "* * * * *", callback)
    assert job.schedule_type == ScheduleType.RECURRING
    assert job.cron_expression == "* * * * *"

@pytest.mark.asyncio
async def test_scheduler_schedule_interval(scheduler):
    callback = MagicMock()
    job = scheduler.schedule_interval("int1", "Int Job", 60, callback)
    assert job.schedule_type == ScheduleType.INTERVAL
    assert job.interval_seconds == 60

@pytest.mark.asyncio
async def test_scheduler_control_methods(scheduler):
    callback = MagicMock()
    scheduler.schedule_once("c1", "Ctrl Job", datetime.now(UTC) + timedelta(hours=1), callback)
    
    assert scheduler.pause_job("c1") is True
    assert scheduler.get_job("c1").enabled is False
    
    assert scheduler.resume_job("c1") is True
    assert scheduler.get_job("c1").enabled is True
    
    assert scheduler.cancel_job("c1") is True
    assert scheduler.get_job("c1") is None

@pytest.mark.asyncio
async def test_scheduler_reschedule(scheduler):
    callback = MagicMock()
    scheduler.schedule_once("r1", "Resched Job", datetime.now(UTC) + timedelta(hours=1), callback)
    
    new_time = datetime.now(UTC) + timedelta(hours=2)
    assert scheduler.reschedule_job("r1", new_time) is True
    assert scheduler.get_job("r1").scheduled_at == new_time

@pytest.mark.asyncio
async def test_scheduler_reschedule_invalid(scheduler):
    callback = MagicMock()
    scheduler.schedule_interval("r2", "Interval", 60, callback)
    assert scheduler.reschedule_job("r2", datetime.now(UTC)) is False

@pytest.mark.asyncio
async def test_scheduler_get_pending_and_campaign(scheduler):
    callback = MagicMock()
    scheduler.schedule_once("p1", "Pending", datetime.now(UTC) + timedelta(hours=1), callback, campaign_id="camp1")
    
    assert len(scheduler.get_pending_jobs()) == 1
    assert len(scheduler.get_jobs_by_campaign("camp1")) == 1

@pytest.mark.asyncio
async def test_scheduler_execute_job_sync(scheduler):
    # Test sync callback
    results = []
    def sync_cb(val): results.append(val)
    
    # We call _execute_job directly to avoid waiting for actual schedule
    scheduler._callbacks["sync1"] = sync_cb
    scheduler._jobs["sync1"] = MagicMock(metadata={"val": 123})
    
    scheduler._execute_job("sync1")
    assert results == [123]

@pytest.mark.asyncio
async def test_scheduler_execute_job_async(scheduler):
    # Test async callback
    results = []
    async def async_cb(val): results.append(val)
    
    scheduler._callbacks["async1"] = async_cb
    scheduler._jobs["async1"] = MagicMock(metadata={"val": 456})
    
    # In async mode, it creates a task
    scheduler._execute_job("async1")
    # Give it a tick to run
    await asyncio.sleep(0.1)
    assert results == [456]

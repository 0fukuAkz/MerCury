"""Tests for the campaign worker tier (mercury.worker).

The live worker path (consuming from Redis and emitting via the message queue)
is integration-verified under D3; here arq and the execution path are mocked so
the enqueue side, the flag, and the job wrapper are unit-tested without Redis.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from mercury.worker import queue as wq


def test_worker_mode_disabled_by_default(monkeypatch):
    monkeypatch.delenv("CAMPAIGN_EXECUTION_MODE", raising=False)
    assert wq.worker_mode_enabled() is False


def test_worker_mode_toggles_with_env(monkeypatch):
    monkeypatch.setenv("CAMPAIGN_EXECUTION_MODE", "worker")
    assert wq.worker_mode_enabled() is True
    monkeypatch.setenv("CAMPAIGN_EXECUTION_MODE", "inprocess")
    assert wq.worker_mode_enabled() is False


def test_queue_redis_url_fallback_chain(monkeypatch):
    monkeypatch.delenv("CAMPAIGN_QUEUE_REDIS", raising=False)
    monkeypatch.setenv("SOCKETIO_MESSAGE_QUEUE", "redis://broker:6379/2")
    assert wq.queue_redis_url() == "redis://broker:6379/2"
    monkeypatch.setenv("CAMPAIGN_QUEUE_REDIS", "redis://q:6379/0")
    assert wq.queue_redis_url() == "redis://q:6379/0"


async def test_enqueue_campaign_pushes_job():
    fake_job = MagicMock(job_id="job-123")
    fake_pool = AsyncMock()
    fake_pool.enqueue_job = AsyncMock(return_value=fake_job)
    fake_pool.close = AsyncMock()
    with patch("arq.create_pool", AsyncMock(return_value=fake_pool)):
        job_id = await wq.enqueue_campaign(7)
    assert job_id == "job-123"
    fake_pool.enqueue_job.assert_awaited_once_with("run_campaign_job", 7)
    fake_pool.close.assert_awaited_once()


async def test_run_campaign_job_invokes_execution():
    from mercury.worker import tasks

    ctx = {"flask_app": MagicMock(), "emit_fn": MagicMock()}
    with patch("mercury.web.events._run_campaign_thread") as mock_run:
        await tasks.run_campaign_job(ctx, 9)
    mock_run.assert_called_once()
    assert mock_run.call_args.args[0] == 9  # campaign_id is first positional


def test_build_emit_fn_noop_without_broker(monkeypatch):
    from mercury.worker import tasks

    monkeypatch.delenv("SOCKETIO_MESSAGE_QUEUE", raising=False)
    emit = tasks._build_emit_fn()
    # No broker → safe no-op (must not raise).
    assert emit("campaign_progress", {"x": 1}) is None

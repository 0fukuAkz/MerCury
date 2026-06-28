"""Cross-runtime emit-bridge seam tests.

Campaign work runs in a threading.Thread (with an asyncio loop); SocketIO
runs in an eventlet greenlet hub. A direct ``sio.emit`` from the foreign
thread silently no-ops, so progress events are funneled through a stdlib
``queue.Queue``: worker threads ``queue_emit(...)`` and a single eventlet
greenlet (``_drain_emit_queue``) drains it and emits on the hub.

The normal suite mocks this bridge entirely. These tests exercise the real
thing — actual threads enqueuing, the real queue, and the drain loop driven
one pass at a time — so the thread-safety guarantee the bridge depends on is
verified rather than assumed.
"""

import queue
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from mercury.web.extensions import _drain_emit_queue, queue_emit, start_emit_bridge


class _BreakLoop(Exception):
    """Sentinel to break out of the otherwise-infinite drain loop in tests."""


def test_queue_emit_enqueues_event():
    fresh: queue.Queue = queue.Queue()
    with patch("mercury.web.extensions._emit_queue", fresh):
        queue_emit("campaign_progress", {"pct": 10})
    assert fresh.get_nowait() == ("campaign_progress", {"pct": 10})


def test_queue_emit_is_thread_safe_under_concurrency():
    """Every event from every worker thread must land — no loss, no crash.

    This is the core guarantee that lets campaign threads emit safely without
    touching the eventlet hub directly.
    """
    fresh: queue.Queue = queue.Queue()

    def worker():
        for i in range(50):
            queue_emit("evt", {"i": i})

    with patch("mercury.web.extensions._emit_queue", fresh):
        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert fresh.qsize() == 200


def test_queue_emit_drops_without_raising_when_full():
    """A full queue (drain greenlet stalled) drops the event, never crashes
    the campaign that's emitting."""
    full: queue.Queue = queue.Queue(maxsize=1)
    full.put_nowait(("already", {}))  # now at capacity
    with patch("mercury.web.extensions._emit_queue", full):
        queue_emit("dropped", {"a": 1})  # must not raise
    assert full.qsize() == 1  # the new event was dropped, not enqueued


def test_event_from_worker_thread_is_drained_and_emitted():
    """End-to-end bridge: a foreign thread enqueues; the drain loop emits it."""
    fresh: queue.Queue = queue.Queue()
    sio = MagicMock()
    sio.sleep.side_effect = _BreakLoop  # break once the queue is empty

    with patch("mercury.web.extensions._emit_queue", fresh):
        producer = threading.Thread(target=queue_emit, args=("campaign_progress", {"pct": 50}))
        producer.start()
        producer.join()

        with pytest.raises(_BreakLoop):
            _drain_emit_queue(sio)

    sio.emit.assert_called_once_with("campaign_progress", {"pct": 50})


def test_drain_swallows_emit_errors_and_keeps_running():
    """A failing sio.emit must not kill the drain greenlet."""
    fresh: queue.Queue = queue.Queue()
    sio = MagicMock()
    sio.emit.side_effect = RuntimeError("hub down")
    sio.sleep.side_effect = _BreakLoop

    with patch("mercury.web.extensions._emit_queue", fresh):
        queue_emit("evt", {})
        with pytest.raises(_BreakLoop):
            _drain_emit_queue(sio)  # error swallowed, loop continued to the empty-sleep

    sio.emit.assert_called_once()  # it tried, and did not propagate the error


def test_start_emit_bridge_spawns_once():
    """Idempotent: multiple init paths must not double-spawn the greenlet."""
    spawned = []
    sio = SimpleNamespace(start_background_task=lambda *a, **k: spawned.append(a))

    start_emit_bridge(sio)
    start_emit_bridge(sio)

    assert len(spawned) == 1
    assert sio._mercury_bridge_started is True

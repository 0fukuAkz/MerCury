"""Tests for retry_queue.py coverage.

Targets missing lines: 47, 107, 175, 179, 201, 214, 250-251, 262-264,
271-281, 285-294, 298-329.
"""

import asyncio
import json
import os
import tempfile
import pytest
from datetime import datetime, UTC, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from mercury.engine.retry_queue import (
    RetryConfig,
    RetryItem,
    RetryQueue,
    RetryStatus,
)


# ---------------------------------------------------------------------------
# RetryItem.to_dict  (line 47)
# ---------------------------------------------------------------------------

class TestRetryItemToDict:
    def test_to_dict_returns_expected_keys(self):
        """Line 47: to_dict must serialise every field."""
        item = RetryItem(
            id="abc-123",
            data={"recipient": "user@example.com"},
            attempt=2,
            max_attempts=5,
            last_error="Connection refused",
            status=RetryStatus.RETRYING,
        )
        d = item.to_dict()

        assert d["id"] == "abc-123"
        assert d["data"] == {"recipient": "user@example.com"}
        assert d["attempt"] == 2
        assert d["max_attempts"] == 5
        assert d["last_error"] == "Connection refused"
        assert d["status"] == "retrying"
        assert "created_at" in d
        assert "next_retry_at" in d

    def test_to_dict_status_value_is_string(self):
        item = RetryItem(id="x", data={}, status=RetryStatus.EXHAUSTED)
        assert item.to_dict()["status"] == "exhausted"

    def test_to_dict_null_last_error(self):
        item = RetryItem(id="y", data={})
        assert item.to_dict()["last_error"] is None


# ---------------------------------------------------------------------------
# RetryQueue with persist_path  (lines 107, 271-329)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestRetryQueuePersistence:
    """Tests for _write_state_to_disk, _load_state and _persist_state."""

    async def test_persist_path_triggers_load_on_init(self):
        """Line 107: when persist_path is given, _load_state is called."""
        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w"
        ) as f:
            # Write an empty-but-valid state file
            json.dump({"items": {}, "stats": {}}, f)
            path = f.name

        try:
            queue = RetryQueue(
                config=RetryConfig(max_attempts=3),
                persist_path=path,
            )
            # If _load_state ran without error the queue object is valid
            assert queue.persist_path == path
        finally:
            os.unlink(path)

    async def test_write_state_to_disk_creates_file(self):
        """Lines 285-294: _write_state_to_disk writes valid JSON atomically."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "state.json")
            queue = RetryQueue(config=RetryConfig(), persist_path=path)

            state = {"items": {}, "stats": {"total_added": 0}}
            queue._write_state_to_disk(state)

            assert os.path.exists(path)
            with open(path) as f:
                loaded = json.load(f)
            assert loaded["stats"]["total_added"] == 0

    async def test_write_state_to_disk_raises_on_bad_path(self):
        """_write_state_to_disk propagates errors when path is invalid."""
        queue = RetryQueue(
            config=RetryConfig(),
            persist_path="/nonexistent_dir/state.json",
        )
        with pytest.raises(Exception):
            queue._write_state_to_disk({"items": {}, "stats": {}})

    async def test_load_state_restores_items(self):
        """Lines 298-329: _load_state populates _items and _queue."""
        item = RetryItem(
            id="persisted-1",
            data={"email": "a@b.com"},
            attempt=1,
            max_attempts=3,
            status=RetryStatus.PENDING,
        )
        state = {
            "items": {"persisted-1": item.to_dict()},
            "stats": {
                "total_added": 1,
                "total_retried": 0,
                "total_success": 0,
                "total_failed": 0,
                "total_exhausted": 0,
            },
        }

        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w"
        ) as f:
            json.dump(state, f)
            path = f.name

        try:
            queue = RetryQueue(config=RetryConfig(), persist_path=path)
            assert "persisted-1" in queue._items
            assert queue.stats["total_added"] == 1
        finally:
            os.unlink(path)

    async def test_load_state_skips_success_and_exhausted(self):
        """Lines 321-323: SUCCESS and EXHAUSTED items must not be re-loaded."""
        items_data = {}
        for sid, status in [
            ("s1", RetryStatus.SUCCESS),
            ("s2", RetryStatus.EXHAUSTED),
            ("s3", RetryStatus.PENDING),
        ]:
            ri = RetryItem(id=sid, data={}, status=status)
            items_data[sid] = ri.to_dict()

        state = {"items": items_data, "stats": {}}

        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w"
        ) as f:
            json.dump(state, f)
            path = f.name

        try:
            queue = RetryQueue(config=RetryConfig(), persist_path=path)
            assert "s1" not in queue._items
            assert "s2" not in queue._items
            assert "s3" in queue._items
        finally:
            os.unlink(path)

    async def test_load_state_missing_file_does_not_raise(self):
        """Lines 302-304: if the file does not exist, _load_state is a no-op."""
        queue = RetryQueue(
            config=RetryConfig(),
            persist_path="/tmp/nonexistent_mercury_test_state.json",
        )
        # No exception; _items is empty
        assert len(queue._items) == 0

    async def test_persist_state_writes_current_items(self):
        """Lines 271-281: _persist_state serialises _items to disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "state.json")
            config = RetryConfig(max_attempts=3, base_delay=0.01, max_delay=0.1)
            queue = RetryQueue(config=config, persist_path=path)

            await queue.add("p1", {"x": 1}, error="err")
            # _persist_state is called inside add; file should exist
            assert os.path.exists(path)

            with open(path) as f:
                data = json.load(f)
            assert "p1" in data["items"]

    async def test_load_state_handles_corrupt_file(self):
        """Lines 328-329: corrupt JSON logs error but does not raise."""
        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w"
        ) as f:
            f.write("THIS IS NOT JSON {{{")
            path = f.name

        try:
            # Should not raise despite corrupt file
            queue = RetryQueue(config=RetryConfig(), persist_path=path)
            assert len(queue._items) == 0
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# get_ready: skips items not in _items  (line 175)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestGetReady:
    async def test_get_ready_skips_stale_heap_entries(self):
        """Line 175: if item.id is not in _items the heap entry is skipped."""
        config = RetryConfig(max_attempts=3, base_delay=0.0)
        queue = RetryQueue(config=config)

        # Manually craft a stale heap entry with a past next_retry_at
        import heapq
        stale = RetryItem(id="ghost", data={})
        stale.next_retry_at = datetime.now(UTC) - timedelta(seconds=10)
        heapq.heappush(queue._queue, stale)
        # Do NOT add to _items — simulates a stale reference

        ready = await queue.get_ready()
        assert all(r.id != "ghost" for r in ready)

    async def test_get_ready_skips_exhausted_items(self):
        """Line 179: EXHAUSTED items in the heap must be skipped."""
        config = RetryConfig(max_attempts=3, base_delay=0.0)
        queue = RetryQueue(config=config)

        import heapq
        exhausted = RetryItem(id="ex1", data={}, status=RetryStatus.EXHAUSTED)
        exhausted.next_retry_at = datetime.now(UTC) - timedelta(seconds=10)
        # Add to both _items and the heap so it passes the id check
        queue._items["ex1"] = exhausted
        heapq.heappush(queue._queue, exhausted)

        ready = await queue.get_ready()
        assert all(r.id != "ex1" for r in ready)


# ---------------------------------------------------------------------------
# mark_failed with non-existent id  (line 201)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestMarkFailed:
    async def test_mark_failed_nonexistent_id_returns_silently(self):
        """Line 201: mark_failed on unknown id must not raise."""
        queue = RetryQueue(config=RetryConfig())
        # Should return without raising
        await queue.mark_failed("does-not-exist", "some error")
        # Stats should remain at zero
        assert queue.stats["total_failed"] == 0


# ---------------------------------------------------------------------------
# start when already running  (line 214)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestStart:
    async def test_start_when_already_running_returns_early(self):
        """Line 214: calling start() twice must not create a second task."""
        config = RetryConfig(max_attempts=3, base_delay=0.1, process_interval=0.1)
        queue = RetryQueue(config=config)

        await queue.start()
        first_task = queue._process_task

        # Second call should return early
        await queue.start()
        second_task = queue._process_task

        assert first_task is second_task

        await queue.stop()


# ---------------------------------------------------------------------------
# _process_loop: handler returns True  (lines 250-251)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestProcessLoopHandlerSuccess:
    async def test_process_loop_marks_success_when_handler_returns_true(self):
        """Lines 246-247 / 250-251: mark_success called when handler returns True."""
        config = RetryConfig(
            max_attempts=3,
            base_delay=0.0,
            max_delay=0.01,
            process_interval=0.05,
        )

        calls = []

        async def succeeding_handler(data: dict) -> bool:
            calls.append(data)
            return True

        queue = RetryQueue(config=config, handler=succeeding_handler)
        await queue.start()

        await queue.add("ok-item", {"v": 1}, error="initial error")

        # Give the loop time to pick up and process the item
        await asyncio.sleep(0.4)

        await queue.stop()

        assert queue.stats["total_success"] >= 1
        assert len(calls) >= 1

    async def test_process_loop_marks_failed_when_handler_returns_false(self):
        """Lines 249: mark_failed called when handler returns False."""
        config = RetryConfig(
            max_attempts=1,
            base_delay=0.0,
            max_delay=0.01,
            process_interval=0.05,
        )

        async def failing_handler(data: dict) -> bool:
            return False

        queue = RetryQueue(config=config, handler=failing_handler)
        await queue.start()

        await queue.add("fail-item", {"v": 2}, error="initial")

        await asyncio.sleep(0.4)

        await queue.stop()

        assert queue.stats["total_failed"] >= 1

    async def test_process_loop_handles_handler_exception(self):
        """Lines 250-251: exceptions from handler call mark_failed."""
        config = RetryConfig(
            max_attempts=1,
            base_delay=0.0,
            max_delay=0.01,
            process_interval=0.05,
        )

        async def raising_handler(data: dict) -> bool:
            raise RuntimeError("boom")

        queue = RetryQueue(config=config, handler=raising_handler)
        await queue.start()

        await queue.add("ex-item", {"v": 3}, error="initial")

        await asyncio.sleep(0.4)

        await queue.stop()

        # mark_failed is called which re-adds to the queue; total_failed >= 1
        assert queue.stats["total_failed"] >= 1

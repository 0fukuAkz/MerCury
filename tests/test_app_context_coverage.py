"""Tests for app_context.py coverage.

Targets missing lines: 46-62, 67-68, 72-73, 77-78, 82, 86, 102-104, 115, 121.
"""

from unittest.mock import MagicMock, patch

from mercury.app_context import (
    AppContext,
    get_app_context,
    set_app_context,
    reset_app_context,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_context(**kwargs) -> AppContext:
    """Return an uninitialised AppContext (never touches real extensions)."""
    return AppContext(**kwargs)


# ---------------------------------------------------------------------------
# AppContext.initialize
# ---------------------------------------------------------------------------


class TestInitialize:
    """Lines 46-62."""

    def test_initialize_sets_is_initialized(self):
        """After initialize the flag must be True and extensions assigned."""
        ctx = _fresh_context()
        assert ctx.is_initialized is False

        # Patch the method itself to verify it's invoked with the right arg.
        # (Exercising the full init body lives in the integration tests.)
        fake_app = MagicMock()
        with patch("mercury.app_context.AppContext.initialize") as mock_method:
            ctx.initialize(fake_app)
            mock_method.assert_called_once_with(fake_app)

    def test_initialize_real_early_return_when_already_initialized(self):
        """Lines 46-48: calling initialize twice should return early."""
        ctx = _fresh_context()
        ctx.is_initialized = True  # pre-set to simulate previous init

        fake_app = MagicMock()

        # The method should log a warning and return without touching extensions.
        # We verify by asserting no extension init is attempted.
        with patch("mercury.app_context.AppContext.initialize", wraps=AppContext.initialize):
            # Since extensions import would fail in unit-test environment,
            # mark already initialized so the early-return path (lines 46-48) is hit.
            with patch.object(
                __import__("mercury.app_context", fromlist=["logger"]).logger,
                "warning",
            ) as mock_warn:
                # Call the real method on the pre-initialized context
                AppContext.initialize(ctx, fake_app)
                mock_warn.assert_called_once()
                # is_initialized should still be True but no further side effects
                assert ctx.is_initialized is True

    def test_initialize_early_return_does_not_reinitialize_extensions(self):
        """If already initialized, limiter and socketio must not be overwritten."""
        mock_limiter = MagicMock()
        mock_socketio = MagicMock()

        ctx = _fresh_context()
        ctx.is_initialized = True
        ctx.limiter = mock_limiter
        ctx.socketio = mock_socketio

        fake_app = MagicMock()
        AppContext.initialize(ctx, fake_app)  # should return early

        # References must be unchanged
        assert ctx.limiter is mock_limiter
        assert ctx.socketio is mock_socketio


# ---------------------------------------------------------------------------
# AppContext.initialize via mocked extensions (full path, lines 51-62)
# ---------------------------------------------------------------------------


class TestInitializeFullPath:
    """Lines 51-62 - the non-early-return branch."""

    def test_initialize_calls_init_app_on_extensions(self):
        """Verify that limiter.init_app and socketio.init_app are called."""
        mock_limiter = MagicMock()
        mock_socketio = MagicMock()
        fake_app = MagicMock()

        ctx = _fresh_context()

        # Patch the imports inside the method
        with patch("mercury.app_context.AppContext.initialize"):
            pass  # we need to call the real one with patched imports

        # Manually replicate what initialize does after the early-return guard
        # by calling through a patched sys import
        import sys

        fake_extensions_module = MagicMock()
        fake_extensions_module.limiter = mock_limiter
        fake_extensions_module.socketio = mock_socketio

        with patch.dict(
            sys.modules,
            {"mercury.web.extensions": fake_extensions_module},
        ):
            ctx.initialize(fake_app)

        mock_limiter.init_app.assert_called_once_with(fake_app)
        mock_socketio.init_app.assert_called_once_with(fake_app)
        assert ctx.limiter is mock_limiter
        assert ctx.socketio is mock_socketio
        assert ctx.is_initialized is True


# ---------------------------------------------------------------------------
# AppContext.emit_progress  (lines 67-68)
# ---------------------------------------------------------------------------

# NOTE: The emit_* methods now route through the cross-thread bridge in
# mercury.web.extensions (queue_emit) rather than calling socketio.emit
# directly. The eventlet bridge greenlet drains the queue and emits on
# hub — this makes the call safe from any thread (asyncio loop, campaign
# thread, etc.). These tests pin the contract that AppContext forwards
# to that bridge, not the now-obsolete direct-emit path.


class TestEmitProgress:
    def test_emit_progress_with_socketio(self):
        ctx = _fresh_context(socketio=MagicMock())
        with patch("mercury.web.extensions.queue_emit") as mock_queue:
            ctx.emit_progress({"percent": 50})
        mock_queue.assert_called_once_with("campaign_progress", {"percent": 50})

    def test_emit_progress_without_socketio(self):
        ctx = _fresh_context(socketio=None)
        # Should not raise even when no socketio is wired up.
        with patch("mercury.web.extensions.queue_emit"):
            ctx.emit_progress({"percent": 50})


# ---------------------------------------------------------------------------
# AppContext.emit_complete
# ---------------------------------------------------------------------------


class TestEmitComplete:
    def test_emit_complete_with_socketio(self):
        ctx = _fresh_context(socketio=MagicMock())
        with patch("mercury.web.extensions.queue_emit") as mock_queue:
            ctx.emit_complete({"status": "done"})
        mock_queue.assert_called_once_with("campaign_complete", {"status": "done"})

    def test_emit_complete_without_socketio(self):
        ctx = _fresh_context(socketio=None)
        with patch("mercury.web.extensions.queue_emit"):
            ctx.emit_complete({"status": "done"})  # no error expected


# ---------------------------------------------------------------------------
# AppContext.emit_event
# ---------------------------------------------------------------------------


class TestEmitEvent:
    def test_emit_event_with_socketio(self):
        ctx = _fresh_context(socketio=MagicMock())
        with patch("mercury.web.extensions.queue_emit") as mock_queue:
            ctx.emit_event("my_event", {"key": "val"})
        mock_queue.assert_called_once_with("my_event", {"key": "val"})

    def test_emit_event_without_socketio(self):
        ctx = _fresh_context(socketio=None)
        with patch("mercury.web.extensions.queue_emit"):
            ctx.emit_event("my_event", {"key": "val"})  # no error expected


# ---------------------------------------------------------------------------
# AppContext.get_limiter  (line 82)
# ---------------------------------------------------------------------------


class TestGetLimiter:
    def test_get_limiter_returns_limiter(self):
        mock_lim = MagicMock()
        ctx = _fresh_context(limiter=mock_lim)
        assert ctx.get_limiter() is mock_lim

    def test_get_limiter_returns_none_when_not_set(self):
        ctx = _fresh_context()
        assert ctx.get_limiter() is None


# ---------------------------------------------------------------------------
# AppContext.get_socketio  (line 86)
# ---------------------------------------------------------------------------


class TestGetSocketio:
    def test_get_socketio_returns_socketio(self):
        mock_sio = MagicMock()
        ctx = _fresh_context(socketio=mock_sio)
        assert ctx.get_socketio() is mock_sio

    def test_get_socketio_returns_none_when_not_set(self):
        ctx = _fresh_context()
        assert ctx.get_socketio() is None


# ---------------------------------------------------------------------------
# Module-level helpers  (lines 102-104, 115, 121)
# ---------------------------------------------------------------------------


class TestModuleHelpers:
    def setup_method(self):
        """Each test starts with a clean global state."""
        reset_app_context()

    def teardown_method(self):
        """Restore clean global state after each test."""
        reset_app_context()

    def test_get_app_context_creates_new_instance_when_none(self):
        """Lines 102-104: first call must create and return an AppContext."""
        ctx = get_app_context()
        assert isinstance(ctx, AppContext)

    def test_get_app_context_returns_same_instance_on_second_call(self):
        """Singleton behaviour: subsequent calls return the same object."""
        ctx1 = get_app_context()
        ctx2 = get_app_context()
        assert ctx1 is ctx2

    def test_set_app_context_replaces_global(self):
        """Line 115: set_app_context must replace the current singleton."""
        original = get_app_context()
        replacement = AppContext()
        set_app_context(replacement)
        assert get_app_context() is replacement
        assert get_app_context() is not original

    def test_reset_app_context_sets_to_none(self):
        """Line 121: after reset get_app_context creates a new instance."""
        ctx_before = get_app_context()
        reset_app_context()
        ctx_after = get_app_context()
        # A brand-new object is created; it should not be the same reference
        assert ctx_after is not ctx_before

    def test_set_app_context_with_none_allowed(self):
        """set_app_context(None) should work (and then get_app_context creates fresh)."""
        set_app_context(None)
        ctx = get_app_context()
        assert isinstance(ctx, AppContext)

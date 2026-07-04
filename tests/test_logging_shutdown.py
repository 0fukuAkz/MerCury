"""Regression test: eventlet-patched shutdown must be traceback-free.

Guards the fix in ``mercury.utils.logging_config._teardown_logging_handlers``.

Under gunicorn's eventlet worker, ``threading`` is monkey-patched, so the
stdlib logging lock uses eventlet's *green* ``get_ident``. At interpreter
shutdown the logging handler weakref finalizers (``logging._removeHandlerRef``)
can run *after* greenlet's C-extension has finalized and raise
``RuntimeError: greenlet is being finalized`` — printed as a harmless but noisy
``Exception ignored in:`` line. The fix nulls ``logging._lock`` from an
``atexit`` hook so those finalizers run lock-free and never touch the dead
greenlet.
"""

import subprocess
import sys
import textwrap

import pytest

pytest.importorskip("eventlet")


def test_eventlet_shutdown_has_no_greenlet_finalized_traceback():
    """A monkey-patched process that configures logging exits without the noise.

    Runs in a subprocess so ``eventlet.monkey_patch()`` (which mutates the
    interpreter's threading) can't leak into the test process, and so a real
    interpreter shutdown actually occurs.
    """
    script = textwrap.dedent(
        """
        import eventlet
        eventlet.monkey_patch()

        import logging
        from mercury.utils.logging_config import configure_logging

        configure_logging(level="INFO")
        logging.getLogger("shutdown_test").info("emit one record, then exit")
        """
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=60,
    )

    # The process must exit cleanly...
    assert proc.returncode == 0, f"non-zero exit ({proc.returncode}); stderr:\n{proc.stderr}"
    # ...and the eventlet/logging finalizer race must not appear at teardown.
    assert "greenlet is being finalized" not in proc.stderr, (
        "shutdown emitted the eventlet+logging finalizer race that "
        f"_teardown_logging_handlers is meant to suppress; stderr was:\n{proc.stderr}"
    )

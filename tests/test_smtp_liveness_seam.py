"""Real-socket SMTP liveness seam test.

The connection-pool unit tests mock ``is_alive()``; this drives the NOOP
pre-ping against a genuine in-process SMTP server (aiosmtpd) so the
stale-connection fix is verified end-to-end over a real socket — the seam
the "SMTP server not responding to commands" incident lived in, and which a
mocked probe can never exercise.
"""

import socket

import pytest
from aiosmtpd.controller import Controller
from aiosmtpd.handlers import Sink

from mercury.engine.connection_pool import AsyncConnectionPool, SMTPServerConfig


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def smtp_server():
    """In-process SMTP server that accepts and discards mail (Sink handler).

    aiosmtpd 1.4.x's readiness check connects to the configured port, which
    fails with port=0, so we pre-allocate a concrete free port.
    """
    # ready_timeout defaults to 1.0s; bump it generously so the readiness
    # handshake doesn't spuriously time out (surfacing as a fixture ERROR) when
    # the suite is under heavy load and the server thread is slow to come up.
    controller = Controller(Sink(), hostname="127.0.0.1", port=_free_port(), ready_timeout=30.0)
    controller.start()
    try:
        yield controller
    finally:
        controller.stop()


def _config(controller) -> SMTPServerConfig:
    return SMTPServerConfig(
        name="fake-smtp",
        host=controller.hostname,
        port=controller.port,
        tls_mode="none",
        use_auth=False,
        timeout=5,
    )


async def test_is_alive_true_live_then_false_after_socket_dies(smtp_server):
    """is_alive() NOOPs a real socket: True while live, False once it's dead."""
    pool = AsyncConnectionPool(_config(smtp_server), pool_size=1)
    conn = await pool.get_connection()
    try:
        assert await conn.is_alive() is True  # real NOOP against the live server

        conn.client.close()  # kill the underlying socket (peer-gone simulation)
        assert await conn.is_alive() is False
        assert conn.is_connected is False  # marked dead so the pool discards it
    finally:
        await pool.close_all()


async def test_pool_prepings_discards_dead_conn_and_reopens(smtp_server):
    """A pooled connection that died while idle is pre-pinged on checkout,
    discarded, and replaced with a fresh working one — against a real server.

    pool_size=1 is deliberate: with a larger pool the second checkout could
    grab a *different* seeded connection and pass for the wrong reason. With
    exactly one slot, a fresh conn can only appear if the dead one was truly
    discarded. threshold=-1 forces the pre-ping on every checkout so the test
    is deterministic without sleeping past a real idle window.
    """
    pool = AsyncConnectionPool(_config(smtp_server), pool_size=1, pre_ping_idle_threshold=-1.0)

    conn1 = await pool.get_connection()
    await pool.release_connection(conn1)

    # The exact stale-connection bug: socket is dead but is_connected reads True.
    conn1.client.close()

    conn2 = await pool.get_connection()
    try:
        assert conn2 is not conn1  # the dead one was discarded, not reused
        assert conn1 not in pool.connections  # ...and dropped from the pool
        assert await conn2.is_alive() is True  # the replacement really works
    finally:
        await pool.close_all()

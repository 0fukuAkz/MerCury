"""Web layer - Flask web UI with WebSocket support."""


def create_app(*args, **kwargs):
    """Lazy wrapper to avoid importing app module at package load time.

    This prevents the RuntimeWarning when running with python -m mercury.web.app,
    which occurs when mercury.web.app appears in sys.modules before execution.
    """
    from .app import create_app as _create_app
    return _create_app(*args, **kwargs)


__all__ = ["create_app"]


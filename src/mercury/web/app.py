"""Main application factory."""

# NOTE: do NOT call eventlet.monkey_patch() here. Tried in a previous
# debug round — it broke the asyncio background loop (asyncio.run_
# coroutine_threadsafe deadlocks once threading.Lock is greenlet-backed),
# and the campaign send pipeline hung before reaching the progress
# callback. Cross-thread SocketIO emits are now bridged through a
# thread-safe queue drained by an eventlet greenlet (see
# web/extensions.py: emit_bridge), avoiding the conflict entirely.

import os
import logging
from typing import Optional
from flask import Flask
from flask_login import LoginManager
from alembic.config import Config as AlembicConfig
from alembic import command as alembic_command

from ..app_context import AppContext, get_app_context, set_app_context
from ..utils.logging_config import configure_logging
from ..utils.app_dirs import get_log_dir
from ..data.database import init_db
from ..security.auth import get_user_by_id, init_auth

# Import extensions (limiter, socketio)
from .extensions import socketio, start_background_loop
from .events import register_socketio_events

# Monkey-patch eventlet websocket to suppress noisy EBADF logs on disconnect
try:
    import errno
    import socket
    import eventlet.websocket

    def _safe_shutdown(self, e_frame, *args, **kwargs):
        try:
            e_frame(*args, **kwargs)
            self.socket.shutdown(socket.SHUT_WR)
        except OSError as e:
            err = getattr(e, "errno", None)
            if err is None and e.args:
                err = e.args[0]
            if err not in (errno.ENOTCONN, errno.EBADF) and "Bad file descriptor" not in str(e):
                self.log.write(
                    "{ctx} socket shutdown error: {e}\n".format(ctx=self.log_context, e=e)
                )
        except Exception:
            pass
        finally:
            self.socket.close()

    def _quiet_close_legacy(self):
        _safe_shutdown(self, self._send_closing_frame, True)

    def _quiet_close_rfc(self, close_data=None):
        _safe_shutdown(
            self, self._send_closing_frame, close_data=close_data, ignore_send_errors=True
        )

    eventlet.websocket.WebSocket.close = _quiet_close_legacy
    if hasattr(eventlet.websocket, "RFC6455WebSocket"):
        eventlet.websocket.RFC6455WebSocket.close = _quiet_close_rfc
except ImportError:
    pass

# Import routes
from .routes.auth import auth_bp
from .routes.api import api_bp
from .routes.views import views_bp
from .routes.tracking import tracking_bp
from .routes.health import health_bp
from .routes.tools import tools_bp
from .routes.settings import settings_bp
from .routes.senders import senders_bp
from .routes.templates import templates_bp
from .routes.attachments import attachments_bp

logger = logging.getLogger(__name__)


def create_app(config: Optional[dict] = None, app_context: Optional[AppContext] = None) -> Flask:
    """
    Create and configure Flask application.

    Args:
        config: Optional configuration dictionary
        app_context: Optional pre-configured context (for testing)

    Returns:
        Configured Flask application
    """
    app = Flask(__name__)

    # Configuration
    app.config["ENV"] = os.environ.get("FLASK_ENV", "development")
    app.config["DEBUG"] = os.environ.get("FLASK_DEBUG", "0").lower() in ("true", "1")
    _flask_env = os.environ.get("FLASK_ENV", "development").lower()
    _is_production = _flask_env == "production"
    _dev_envs = {"development", "dev", "test", "testing", "local"}
    _explicit_dev = _flask_env in _dev_envs

    # SECRET_KEY: required if not in an explicit dev environment. No default;
    # no `MERCURY_DEV` escape hatch. If you need a key for `make dev`, set
    # `FLASK_ENV=development` (which is the default anyway) and set
    # `SECRET_KEY` to anything.
    _secret_key = os.environ.get("SECRET_KEY")
    if not _secret_key:
        if not _explicit_dev:
            raise RuntimeError(
                "SECRET_KEY is not set. Generate one with "
                "`python -c 'import secrets; print(secrets.token_hex(32))'` and "
                f"export it. Or set FLASK_ENV to one of {sorted(_dev_envs)} for "
                "local iteration."
            )
        _secret_key = "dev-secret-key-DO-NOT-USE-IN-PROD"
    app.config["SECRET_KEY"] = _secret_key

    # Production env-var preflight: surface common mis-configurations at boot
    # rather than failing in surprising ways much later.
    if _is_production:
        if "ADMIN_PASSWORD" not in os.environ:
            raise RuntimeError(
                "ADMIN_PASSWORD is not set and FLASK_ENV=production. Refusing "
                "to boot with the default 'admin' bootstrap password."
            )
        _prod_warnings: list[str] = []
        if not os.environ.get("API_KEYS", "").strip():
            _prod_warnings.append("API_KEYS not set — programmatic API access will be disabled.")
        _rls = os.environ.get("RATE_LIMIT_STORAGE", "memory://")
        if _rls.startswith("memory://"):
            _prod_warnings.append(
                "RATE_LIMIT_STORAGE is in-memory — limits reset on restart and are "
                "not shared across workers. Use a redis:// URL in production."
            )
        for _w in _prod_warnings:
            logger.warning("Production preflight: %s", _w)
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB max upload

    # Session cookie hardening.
    # - HttpOnly always (defense against XSS reading session cookie).
    # - SameSite=Lax always (CSRF mitigation for cross-site form posts).
    # - Secure only in production (dev usually runs over plain http://).
    # Operators can override SESSION_COOKIE_SECURE via env if running TLS-terminated
    # behind a proxy in non-prod, or vice versa.
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = os.environ.get("SESSION_COOKIE_SAMESITE", "Lax")
    _cookie_secure_env = os.environ.get("SESSION_COOKIE_SECURE")
    if _cookie_secure_env is not None:
        app.config["SESSION_COOKIE_SECURE"] = _cookie_secure_env.lower() in ("1", "true", "yes")
    else:
        app.config["SESSION_COOKIE_SECURE"] = _is_production
    app.config["REMEMBER_COOKIE_HTTPONLY"] = True
    app.config["REMEMBER_COOKIE_SAMESITE"] = app.config["SESSION_COOKIE_SAMESITE"]
    app.config["REMEMBER_COOKIE_SECURE"] = app.config["SESSION_COOKIE_SECURE"]

    # Force JSON output in production for structured logging (Docker/CloudWatch/ELK)
    is_prod = app.config["ENV"] == "production"
    json_logging = os.environ.get("LOG_JSON_OUTPUT", str(is_prod)).lower() == "true"

    # Initialize logging
    log_file = get_log_dir() / "mercury.log"
    configure_logging(
        level=os.environ.get("LOG_LEVEL", "INFO"), json_output=json_logging, log_file=str(log_file)
    )

    if config:
        app.config.update(config)

    # Ensure instance folder exists
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    # Initialize AppContext (DI container)
    if app_context:
        ctx = app_context
        set_app_context(ctx)
    else:
        ctx = get_app_context()

    # Initialize extensions via AppContext
    # This logic calls init_app on limiter, socketio, and csrf
    ctx.initialize(app)

    # Fallback shim: if AppContext was mocked (tests) so csrf.init_app never
    # ran, the templates still reference {{ csrf_token() }} and would crash
    # with UndefinedError. Register a no-op global in that case so render
    # paths exercised by tests don't break.
    if "csrf_token" not in app.jinja_env.globals:
        app.jinja_env.globals["csrf_token"] = lambda: ""

    # Initialize LoginManager
    login_manager = LoginManager()
    # auth.login assumes auth blueprint prefix is root or handled correctly
    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "info"
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        """Load user by ID for Flask-Login."""
        # get_user_by_id handles its own session
        try:
            return get_user_by_id(int(user_id))
        except Exception as e:
            logger.error(f"Error loading user {user_id}: {e}")
            return None

    # Register Blueprints
    app.register_blueprint(views_bp)  # Root routes
    app.register_blueprint(auth_bp)  # Login/Logout
    app.register_blueprint(api_bp)  # /api/...
    app.register_blueprint(tracking_bp)  # /track/...
    app.register_blueprint(health_bp)  # /live, /ready
    app.register_blueprint(tools_bp)  # /tools
    app.register_blueprint(settings_bp)  # /settings
    app.register_blueprint(senders_bp)  # /senders
    app.register_blueprint(templates_bp)  # /templates
    app.register_blueprint(attachments_bp)  # /attachments

    # Register SocketIO events
    register_socketio_events(socketio)

    # Eagerly start the shared background asyncio loop so the first request
    # doesn't pay the start cost. (run_async() also starts it lazily.)
    start_background_loop()

    # Security response headers. Applied to every response. Conservative by
    # default; operators can override via the documented env vars below.
    _csp = os.environ.get(
        "CONTENT_SECURITY_POLICY",
        # default-src 'self' covers scripts/styles/images/fonts. 'unsafe-inline'
        # is required because the dashboard templates embed inline <script>
        # blocks for SocketIO bootstrap; tighten later by extracting them.
        # cdn.socket.io is whitelisted because base.html loads the socket.io
        # client from that CDN — without it the script silently 404s under
        # CSP and the dashboard's lifecycle buttons (Start/Pause/Resume) fail
        # because `io` is undefined.
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.socket.io; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; "
        "connect-src 'self' ws: wss:; "
        "frame-ancestors 'none'",
    )
    _hsts_max_age = int(os.environ.get("HSTS_MAX_AGE", "31536000"))  # 1 year

    @app.after_request
    def _set_security_headers(response):
        # Resist MIME-sniffing attacks.
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        # Block framing (clickjacking). CSP frame-ancestors covers modern browsers,
        # X-Frame-Options covers older ones.
        response.headers.setdefault("X-Frame-Options", "DENY")
        # Don't leak referrer paths to third parties.
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        # Disable powerful browser features the dashboard doesn't use.
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()"
        )
        # CSP — opt-out by setting CONTENT_SECURITY_POLICY=''.
        if _csp:
            response.headers.setdefault("Content-Security-Policy", _csp)
        # HSTS — only over HTTPS, only in production. Browsers ignore the
        # header on plain HTTP, but skipping it here keeps logs clean.
        if _is_production and _hsts_max_age > 0:
            response.headers.setdefault(
                "Strict-Transport-Security", f"max-age={_hsts_max_age}; includeSubDomains"
            )
        return response

    # Inject ui_theme into every template so base.html can set data-theme
    from ..services.settings_service import SettingsService

    @app.context_processor
    def inject_ui_theme():
        try:
            s = SettingsService.get_settings()
            return {"ui_theme": s.ui_theme or "dark"}
        except Exception:
            return {"ui_theme": "dark"}

    # Initialize Database
    with app.app_context():
        try:
            init_db()

            # --- Run Alembic migrations to head ---
            # Non-production: run on boot (convenient for `make dev` and tests).
            # Production: skip. Run `alembic upgrade head` once out-of-band
            # before workers start — multi-worker boot races are real.
            if not _is_production:
                try:
                    _alembic_ini = os.path.join(
                        os.path.dirname(__file__), "..", "..", "..", "alembic.ini"
                    )
                    _alembic_cfg = AlembicConfig(os.path.abspath(_alembic_ini))
                    alembic_command.upgrade(_alembic_cfg, "head")
                    logger.info("Database migrations applied successfully")
                except Exception as ex:
                    logger.warning(
                        f"Alembic migration failed (may be a fresh DB or already current): {ex}"
                    )
            # --------------------------------------

            # Admin bootstrap: only creates a user when ADMIN_USERNAME and
            # ADMIN_PASSWORD are both set in the environment. There is no
            # admin/admin fallback.
            init_auth(app)

            # Reconcile orphan "sending" campaign rows. If the worker
            # process was killed mid-run (SIGKILL, OOM, container restart),
            # no exception handler ever fired — so the campaign row stays
            # at status='sending' forever, with no thread alive to advance
            # it. This is the last hole in the "stuck at sending" bug
            # class: the run thread only updates DB at completion or in
            # an exception, and a hard crash satisfies neither.
            #
            # At boot the `_active_services` dict is always empty, so any
            # row claiming 'sending' must be orphaned. Flip it to 'failed'
            # with a clear note in the log so operators can see what
            # happened.
            try:
                from datetime import datetime, UTC
                from ..data.repositories import CampaignRepository
                from ..data.models.campaign import CampaignStatus
                from ..data.database import get_session_direct as _gsd

                _s = _gsd()
                try:
                    _repo = CampaignRepository(_s)
                    _stale = _repo.get_by_status(CampaignStatus.SENDING)
                    for _c in _stale:
                        logger.warning(
                            "Reconciling orphaned campaign %s (%r) — left at "
                            "status='sending' from a previous run that didn't "
                            "shut down cleanly. Marking as FAILED.",
                            _c.id,
                            _c.name,
                        )
                        _c.status = CampaignStatus.FAILED
                        _c.completed_at = datetime.now(UTC)
                        _repo.update(_c)
                finally:
                    _s.close()
            except Exception as _ex:
                # Reconciliation is best-effort — don't block boot on it.
                logger.warning("Stale-campaign reconciliation skipped: %s", _ex)

        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")


        # --- Start DeadLetterWorker background thread ---
        if not app.config.get("TESTING"):
            _is_reloader = os.environ.get("WERKZEUG_RUN_MAIN")
            if not app.config.get("DEBUG") or _is_reloader == "true":
                def _run_dead_letter_worker(flask_app):
                    import asyncio
                    from ..engine.dead_letter_worker import DeadLetterWorker
                    
                    async def _main():
                        worker = DeadLetterWorker()
                        await worker.start()
                        try:
                            while True:
                                await asyncio.sleep(3600)
                        except asyncio.CancelledError:
                            await worker.stop()
                    
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(_main())
                    
                import threading
                dl_thread = threading.Thread(
                    target=_run_dead_letter_worker,
                    args=(app,),
                    daemon=True,
                    name="DeadLetterWorker"
                )
                dl_thread.start()
                logger.info("DeadLetterWorker daemon thread started")

    logger.info("Application initialized successfully")
    return app


if __name__ == "__main__":
    # Allow running directly with python -m mercury.web.app — bind to all
    # interfaces is intentional for the dev runner so the app is reachable
    # from container/host/VM networks during local iteration. Production uses
    # run.py + gunicorn behind a reverse proxy, not this entry point.
    app = create_app(config={"DEBUG": True})
    socketio.run(app, host="0.0.0.0", port=5000, allow_unsafe_werkzeug=True)  # nosec B104

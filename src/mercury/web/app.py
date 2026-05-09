"""Main application factory."""

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
from ..data.database import init_db, get_session_direct
from ..data.models import User
from ..security.auth import get_user_by_id, hash_password
from ..data.repositories import UserRepository

# Import extensions (limiter, socketio)
from .extensions import socketio, start_background_loop
from .events import register_socketio_events

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
    app.config['ENV'] = os.environ.get('FLASK_ENV', 'development')
    app.config['DEBUG'] = os.environ.get('FLASK_DEBUG', '0').lower() in ('true', '1')
    _secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-prod')
    _flask_env = os.environ.get('FLASK_ENV', 'development').lower()
    _is_production = _flask_env == 'production'
    _default_keys = {'dev-secret-key-change-in-prod', 'prod-secret-key-change-this'}
    # Fail closed on the default SECRET_KEY: only an explicit dev/test env or
    # MERCURY_DEV=1 may run with the dev key. Previously this only fired when
    # FLASK_ENV was *literally* "production" — a typo or unset FLASK_ENV
    # silently shipped the dev key.
    _dev_envs = {'development', 'dev', 'test', 'testing', 'local'}
    _explicit_dev = _flask_env in _dev_envs or os.environ.get('MERCURY_DEV', '').lower() in ('1', 'true', 'yes')
    if _secret_key in _default_keys and not _explicit_dev:
        raise RuntimeError(
            "SECRET_KEY is set to a known insecure default and the environment is not "
            "marked as development. Either set SECRET_KEY to a strong random value, or "
            f"set FLASK_ENV to one of {sorted(_dev_envs)} / set MERCURY_DEV=1 to opt into "
            "the dev key explicitly."
        )
    app.config['SECRET_KEY'] = _secret_key

    # Production env-var preflight: surface common mis-configurations at boot
    # rather than failing in surprising ways much later.
    if _is_production:
        _prod_warnings: list[str] = []
        if 'ADMIN_PASSWORD' not in os.environ:
            _prod_warnings.append(
                "ADMIN_PASSWORD not set — the bootstrap admin will be created with "
                "the well-known default 'admin'. Set ADMIN_PASSWORD before first boot."
            )
        if not os.environ.get('API_KEYS', '').strip():
            _prod_warnings.append(
                "API_KEYS not set — programmatic API access will be disabled."
            )
        _rls = os.environ.get('RATE_LIMIT_STORAGE', 'memory://')
        if _rls.startswith('memory://'):
            _prod_warnings.append(
                "RATE_LIMIT_STORAGE is in-memory — limits reset on restart and are "
                "not shared across workers. Use a redis:// URL in production."
            )
        for _w in _prod_warnings:
            logger.warning("Production preflight: %s", _w)
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload

    # Session cookie hardening.
    # - HttpOnly always (defense against XSS reading session cookie).
    # - SameSite=Lax always (CSRF mitigation for cross-site form posts).
    # - Secure only in production (dev usually runs over plain http://).
    # Operators can override SESSION_COOKIE_SECURE via env if running TLS-terminated
    # behind a proxy in non-prod, or vice versa.
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = os.environ.get('SESSION_COOKIE_SAMESITE', 'Lax')
    _cookie_secure_env = os.environ.get('SESSION_COOKIE_SECURE')
    if _cookie_secure_env is not None:
        app.config['SESSION_COOKIE_SECURE'] = _cookie_secure_env.lower() in ('1', 'true', 'yes')
    else:
        app.config['SESSION_COOKIE_SECURE'] = _is_production
    app.config['REMEMBER_COOKIE_HTTPONLY'] = True
    app.config['REMEMBER_COOKIE_SAMESITE'] = app.config['SESSION_COOKIE_SAMESITE']
    app.config['REMEMBER_COOKIE_SECURE'] = app.config['SESSION_COOKIE_SECURE']
    
    # Force JSON output in production for structured logging (Docker/CloudWatch/ELK)
    is_prod = app.config['ENV'] == 'production'
    json_logging = os.environ.get('LOG_JSON_OUTPUT', str(is_prod)).lower() == 'true'
    
    # Initialize logging
    log_file = get_log_dir() / "mercury.log"
    configure_logging(
        level=os.environ.get('LOG_LEVEL', 'INFO'),
        json_output=json_logging,
        log_file=str(log_file)
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
    if 'csrf_token' not in app.jinja_env.globals:
        app.jinja_env.globals['csrf_token'] = lambda: ''
    
    # Initialize LoginManager
    login_manager = LoginManager()
    # auth.login assumes auth blueprint prefix is root or handled correctly
    login_manager.login_view = 'auth.login' 
    login_manager.login_message_category = 'info'
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
    app.register_blueprint(views_bp) # Root routes
    app.register_blueprint(auth_bp) # Login/Logout
    app.register_blueprint(api_bp) # /api/...
    app.register_blueprint(tracking_bp) # /track/...
    app.register_blueprint(health_bp) # /live, /ready
    app.register_blueprint(tools_bp) # /tools
    app.register_blueprint(settings_bp) # /settings
    app.register_blueprint(senders_bp) # /senders
    app.register_blueprint(templates_bp) # /templates
    
    # Register SocketIO events
    register_socketio_events(socketio)

    # Eagerly start the shared background asyncio loop so the first request
    # doesn't pay the start cost. (run_async() also starts it lazily.)
    start_background_loop()

    # Security response headers. Applied to every response. Conservative by
    # default; operators can override via the documented env vars below.
    _csp = os.environ.get(
        'CONTENT_SECURITY_POLICY',
        # default-src 'self' covers scripts/styles/images/fonts. 'unsafe-inline'
        # is required because the dashboard templates embed inline <script>
        # blocks for SocketIO bootstrap; tighten later by extracting them.
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; "
        "connect-src 'self' ws: wss:; "
        "frame-ancestors 'none'"
    )
    _hsts_max_age = int(os.environ.get('HSTS_MAX_AGE', '31536000'))  # 1 year

    @app.after_request
    def _set_security_headers(response):
        # Resist MIME-sniffing attacks.
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        # Block framing (clickjacking). CSP frame-ancestors covers modern browsers,
        # X-Frame-Options covers older ones.
        response.headers.setdefault('X-Frame-Options', 'DENY')
        # Don't leak referrer paths to third parties.
        response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
        # Disable powerful browser features the dashboard doesn't use.
        response.headers.setdefault(
            'Permissions-Policy',
            'camera=(), microphone=(), geolocation=(), payment=()'
        )
        # CSP — opt-out by setting CONTENT_SECURITY_POLICY=''.
        if _csp:
            response.headers.setdefault('Content-Security-Policy', _csp)
        # HSTS — only over HTTPS, only in production. Browsers ignore the
        # header on plain HTTP, but skipping it here keeps logs clean.
        if _is_production and _hsts_max_age > 0:
            response.headers.setdefault(
                'Strict-Transport-Security',
                f'max-age={_hsts_max_age}; includeSubDomains'
            )
        return response

    # Inject ui_theme into every template so base.html can set data-theme
    from ..services.settings_service import SettingsService

    @app.context_processor
    def inject_ui_theme():
        try:
            s = SettingsService.get_settings()
            return {'ui_theme': s.ui_theme or 'dark'}
        except Exception:
            return {'ui_theme': 'dark'}
    
    # Initialize Database
    with app.app_context():
        try:
            init_db()
            
            # --- Run Alembic migrations to head ---
            # Default behavior:
            #   - production: SKIP. Run `alembic upgrade head` once out-of-band
            #     (init container / CI / pre-deploy hook) before workers start.
            #     Multi-worker boot races are real, and the previous always-on
            #     default was only safe because run.py forces -w 1.
            #   - non-production: RUN. Convenient for `make dev` and tests.
            # Override with MERCURY_BOOT_MIGRATIONS=1 (force on) or
            # MERCURY_SKIP_BOOT_MIGRATIONS=1 (force off).
            _force_skip = os.environ.get('MERCURY_SKIP_BOOT_MIGRATIONS', '').lower() in ('1', 'true', 'yes')
            _force_run = os.environ.get('MERCURY_BOOT_MIGRATIONS', '').lower() in ('1', 'true', 'yes')
            if _force_skip:
                _run_boot_migrations = False
            elif _force_run:
                _run_boot_migrations = True
            else:
                _run_boot_migrations = not _is_production
            if _run_boot_migrations:
                try:
                    _alembic_ini = os.path.join(
                        os.path.dirname(__file__), '..', '..', '..', 'alembic.ini'
                    )
                    _alembic_cfg = AlembicConfig(os.path.abspath(_alembic_ini))
                    alembic_command.upgrade(_alembic_cfg, 'head')
                    logger.info("Database migrations applied successfully")
                except Exception as ex:
                    logger.warning(f"Alembic migration failed (may be a fresh DB or already current): {ex}")
            # --------------------------------------
            
            # Create default admin if none exists
            session = get_session_direct()
            try:
                repo = UserRepository(session)
                if not repo.get_admins():
                    logger.info("No admin user found. Creating default 'admin' user.")
                    admin = User(
                        username="admin",
                        email="admin@example.com",
                        is_admin=True,
                        is_active=True
                    )
                    # Use environment variable for initial password, fallback to 'admin'
                    initial_password = os.environ.get("ADMIN_PASSWORD", "admin")
                    _using_default_password = 'ADMIN_PASSWORD' not in os.environ
                    admin.password_hash = hash_password(initial_password)
                    admin.must_change_password = _using_default_password
                    session.add(admin)
                    session.commit()
                    if _using_default_password:
                        logger.warning(
                            "Created default admin user with password 'admin'. "
                            "Set the ADMIN_PASSWORD environment variable and change this immediately."
                        )
                    else:
                        logger.info("Created default admin user with password from ADMIN_PASSWORD env var.")
            finally:
                session.close()

        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
    
    logger.info("Application initialized successfully")
    return app

if __name__ == '__main__':
    # Allow running directly with python -m mercury.web.app
    app = create_app(config={'DEBUG': True})
    socketio.run(app, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)

"""Flask web application with authentication, rate limiting, and WebSocket support."""

import asyncio
import os
import secrets
import logging
from typing import Optional
from datetime import datetime, UTC
from functools import wraps

from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, g
from flask_socketio import SocketIO, emit
from flask_login import login_user, logout_user, login_required, current_user
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from sqlalchemy import text

from ..security.auth import (
    init_auth, login_manager, authenticate, 
    User, create_user, get_user_by_username, require_api_key,
    validate_unsubscribe_token, generate_unsubscribe_token
)
from ..app_context import AppContext, get_app_context

logger = logging.getLogger(__name__)

# For backwards compatibility, expose socketio and limiter via app context
# These are deprecated - use get_app_context() instead
def _get_socketio() -> Optional[SocketIO]:
    """Get socketio from app context (deprecated, use get_app_context())."""
    return get_app_context().socketio

def _get_limiter() -> Optional[Limiter]:
    """Get limiter from app context (deprecated, use get_app_context())."""
    return get_app_context().limiter

# Property-like access for backwards compatibility
socketio = property(lambda self: _get_socketio())
limiter = property(lambda self: _get_limiter())


def create_app(config=None, app_context: Optional[AppContext] = None):
    """
    Create Flask application with all extensions.
    
    Args:
        config: Optional configuration dictionary to override defaults
        app_context: Optional AppContext for dependency injection (uses default if not provided)
        
    Returns:
        Configured Flask application instance
    """
    app = Flask(
        __name__,
        template_folder='templates',
        static_folder='static'
    )
    
    # Security configuration
    app.config['SECRET_KEY'] = os.environ.get(
        'SECRET_KEY',
        secrets.token_hex(32)  # Generate random key if not set
    )
    
    # Warn if using generated key
    if 'SECRET_KEY' not in os.environ:
        logger.warning(
            "Using generated SECRET_KEY. Set SECRET_KEY environment variable for production."
        )
    
    # Session configuration
    app.config['SESSION_COOKIE_SECURE'] = os.environ.get('FLASK_ENV') == 'production'
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    
    if config:
        app.config.update(config)
    
    # Initialize extensions via dependency injection
    init_auth(app)
    
    # Use provided context or get the default one
    ctx = app_context or get_app_context()
    ctx.initialize(app)
    
    # Store context in app for access in routes
    app.extensions['app_context'] = ctx
    
    # Register blueprints and routes
    register_auth_routes(app)
    register_routes(app)
    register_api_routes(app, ctx)
    register_tracking_routes(app)
    register_health_routes(app)
    register_socketio_events(ctx.socketio)
    
    return app


def api_key_or_login_required(f):
    """Decorator requiring API key or login for API endpoints."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check for API key in header
        api_key = request.headers.get('X-API-Key')
        if api_key and require_api_key(api_key):
            return f(*args, **kwargs)
        
        # Fall back to login check
        if not current_user.is_authenticated:
            return jsonify({'error': 'Authentication required'}), 401
        
        return f(*args, **kwargs)
    return decorated_function


def register_auth_routes(app: Flask):
    """
    Register authentication routes.
    
    Includes:
        - /login: User login page and form handler
        - /logout: User logout endpoint
    """
    
    @app.route('/login', methods=['GET', 'POST'])
    def login():
        """
        User login page and authentication handler.
        
        GET: Display login form
        POST: Process login credentials and authenticate user
        
        Form Fields:
            username: User's username
            password: User's password
            remember: Optional checkbox for persistent session
            
        Query Parameters:
            next: URL to redirect to after successful login
            
        Returns:
            GET: Rendered login.html template
            POST (success): Redirect to next URL or index
            POST (failure): Rendered login.html with error message
        """
        if current_user.is_authenticated:
            return redirect(url_for('index'))
        
        if request.method == 'POST':
            username = request.form.get('username', '')
            password = request.form.get('password', '')
            remember = request.form.get('remember', False)
            
            user = authenticate(username, password)
            
            if user:
                login_user(user, remember=remember)
                next_page = request.args.get('next')
                flash('Logged in successfully.', 'success')
                return redirect(next_page or url_for('index'))
            else:
                flash('Invalid username or password.', 'error')
        
        return render_template('login.html')
    
    @app.route('/logout')
    @login_required
    def logout():
        """
        Logout current user and end session.
        
        Requires authentication.
        
        Returns:
            Redirect to login page with logout confirmation message
        """
        logout_user()
        flash('You have been logged out.', 'info')
        return redirect(url_for('login'))


def register_routes(app: Flask):
    """
    Register main web UI routes.
    
    All routes require authentication via @login_required decorator.
    """
    
    @app.route('/')
    @login_required
    def index():
        """
        Main dashboard page.
        
        Displays:
            - Campaign overview and statistics
            - Recent activity
            - Quick action buttons
            
        Returns:
            Rendered index.html template
        """
        return render_template('index.html')
    
    @app.route('/campaigns')
    @login_required
    def campaigns():
        """
        Campaigns list page.
        
        Displays:
            - List of all email campaigns
            - Campaign status, statistics, and actions
            - Links to create new campaigns
            
        Returns:
            Rendered campaigns.html template
        """
        return render_template('campaigns.html')
    
    @app.route('/campaigns/new')
    @login_required
    def new_campaign():
        """
        New campaign creation form.
        
        Displays:
            - Form to create a new email campaign
            - Template selection
            - SMTP configuration
            - Recipient list selection
            
        Returns:
            Rendered campaign_form.html template
        """
        return render_template('campaign_form.html')
    
    @app.route('/smtp')
    @login_required
    def smtp_servers():
        """
        SMTP servers management page.
        
        Displays:
            - List of configured SMTP servers
            - Server status and health
            - Add/edit/delete server options
            - Connection testing
            
        Returns:
            Rendered smtp.html template
        """
        return render_template('smtp.html')
    
    @app.route('/templates')
    @login_required
    def templates():
        """
        Email templates management page.
        
        Displays:
            - List of email templates
            - Template preview
            - Add/edit/delete template options
            - Placeholder documentation
            
        Returns:
            Rendered templates.html template
        """
        return render_template('templates.html')
    
    @app.route('/recipients')
    @login_required
    def recipients():
        """
        Recipients management page.
        
        Displays:
            - Recipient lists
            - Import/export options
            - Suppression list management
            - Recipient statistics
            
        Returns:
            Rendered recipients.html template
        """
        return render_template('recipients.html')
    
    @app.route('/logs')
    @login_required
    def logs():
        """
        System and email logs page.
        
        Displays:
            - Success and failure logs
            - Bounce reports
            - System events
            - Log filtering and search
            
        Returns:
            Rendered logs.html template
        """
        return render_template('logs.html')


def register_api_routes(app: Flask, ctx: Optional[AppContext] = None):
    """
    Register API routes with rate limiting.
    
    Args:
        app: Flask application instance
        ctx: Application context for dependency injection
    """
    # Get context from app extensions if not provided
    if ctx is None:
        ctx = app.extensions.get('app_context') or get_app_context()
    
    limiter = ctx.limiter
    
    @app.route('/api/status')
    def api_status():
        """
        Get system status.
        
        Returns:
            JSON object with status, timestamp, and version.
            
        This is a public endpoint that does not require authentication.
        """
        return jsonify({
            'status': 'ok',
            'timestamp': datetime.now(UTC).isoformat(),
            'version': '2.0.0'
        })
    
    @app.route('/api/campaigns', methods=['GET'])
    @api_key_or_login_required
    @limiter.limit("30/minute")
    def api_list_campaigns():
        """
        List all email campaigns.
        
        Requires:
            Authentication via API key or login session
            
        Rate Limit:
            30 requests per minute
            
        Returns:
            JSON object with 'campaigns' array containing campaign objects
            
        Response Schema:
            {
                "campaigns": [
                    {
                        "id": int,
                        "name": str,
                        "status": str,
                        "sent_count": int,
                        "failed_count": int,
                        ...
                    }
                ]
            }
        """
        from ..services.campaign_service import CampaignService
        
        service = CampaignService()
        service.initialize()
        campaigns = service.list_campaigns()
        
        return jsonify({
            'campaigns': [c.to_dict() for c in campaigns]
        })
    
    @app.route('/api/campaigns', methods=['POST'])
    @api_key_or_login_required
    @limiter.limit("10/minute")
    def api_create_campaign():
        """
        Create a new email campaign.
        
        Requires:
            Authentication via API key or login session
            
        Rate Limit:
            10 requests per minute
            
        Request Body (JSON):
            {
                "name": str (required),
                "description": str,
                "subject": str,
                "from_email": str,
                "from_name": str,
                "template_path": str,
                "recipients_path": str,
                "dry_run": bool (default: true)
            }
            
        Returns:
            201: Campaign created successfully
            400: Invalid request (missing required fields)
            
        Response Schema:
            {
                "success": true,
                "campaign": { ... campaign object ... }
            }
        """
        data = request.json
        
        if not data.get('name'):
            return jsonify({'error': 'Campaign name required'}), 400
        
        from ..services.campaign_service import CampaignService, CampaignConfig
        
        config = CampaignConfig(
            name=data.get('name'),
            description=data.get('description', ''),
            subject=data.get('subject', ''),
            from_email=data.get('from_email', ''),
            from_name=data.get('from_name', ''),
            template_path=data.get('template_path', ''),
            recipients_path=data.get('recipients_path', ''),
            dry_run=data.get('dry_run', True)
        )
        
        service = CampaignService()
        service.initialize()
        campaign = service.create_campaign(config)
        
        return jsonify({
            'success': True,
            'campaign': campaign.to_dict()
        })
    
    @app.route('/api/smtp', methods=['GET'])
    @api_key_or_login_required
    @limiter.limit("30/minute")
    def api_list_smtp():
        """
        List all configured SMTP servers.
        
        Requires:
            Authentication via API key or login session
            
        Rate Limit:
            30 requests per minute
            
        Returns:
            JSON object with 'servers' array containing SMTP server configurations
            
        Note:
            Passwords are not returned in the response for security
        """
        from ..data.database import get_session_direct
        from ..data.repositories import SMTPRepository
        
        session = get_session_direct()
        try:
            repo = SMTPRepository(session)
            servers = repo.get_all()
            return jsonify({
                'servers': [s.to_dict() for s in servers]
            })
        finally:
            session.close()
    
    @app.route('/api/smtp', methods=['POST'])
    @api_key_or_login_required
    @limiter.limit("10/minute")
    def api_add_smtp():
        """
        Add a new SMTP server configuration.
        
        Requires:
            Authentication via API key or login session
            
        Rate Limit:
            10 requests per minute
            
        Request Body (JSON):
            {
                "host": str (required),
                "name": str (optional, defaults to host),
                "port": int (default: 587),
                "username": str,
                "password": str,
                "use_tls": bool (default: true)
            }
            
        Returns:
            201: Server added successfully
            400: Invalid request (missing host)
        """
        data = request.json
        
        if not data.get('host'):
            return jsonify({'error': 'Host required'}), 400
        
        from ..services.smtp_service import SMTPService
        
        service = SMTPService()
        server = service.add_server(
            name=data.get('name', data.get('host')),
            host=data['host'],
            port=data.get('port', 587),
            username=data.get('username', ''),
            password=data.get('password', ''),
            use_tls=data.get('use_tls', True)
        )
        
        return jsonify({
            'success': True,
            'server': server.to_dict()
        })
    
    @app.route('/api/smtp/test/<name>', methods=['POST'])
    @api_key_or_login_required
    @limiter.limit("5/minute")
    def api_test_smtp(name):
        """
        Test connection to a specific SMTP server.
        
        Args:
            name: Name of the SMTP server to test
            
        Requires:
            Authentication via API key or login session
            
        Rate Limit:
            5 requests per minute (limited due to external connections)
            
        Returns:
            JSON object with test results:
            {
                "success": bool,
                "server": str,
                "host": str,
                "port": int,
                "message": str (on success),
                "error": str (on failure)
            }
        """
        from ..services.smtp_service import SMTPService
        from ..data.database import get_session_direct
        from ..data.repositories import SMTPRepository
        
        session = get_session_direct()
        try:
            repo = SMTPRepository(session)
            servers = repo.get_all()
            
            service = SMTPService()
            service.load_from_config([s.get_connection_config() for s in servers])
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(service.test_connection(name))
            loop.close()
            
            return jsonify(result)
        finally:
            session.close()
    
    @app.route('/api/templates', methods=['GET'])
    @api_key_or_login_required
    @limiter.limit("30/minute")
    def api_list_templates():
        """List email templates."""
        from ..data.database import get_session_direct
        from ..data.repositories import TemplateRepository
        
        session = get_session_direct()
        try:
            repo = TemplateRepository(session)
            templates = repo.get_active()
            return jsonify({
                'templates': [t.to_dict() for t in templates]
            })
        finally:
            session.close()
    
    @app.route('/api/templates/preview', methods=['POST'])
    @api_key_or_login_required
    @limiter.limit("20/minute")
    def api_preview_template():
        """Preview template with sample data."""
        data = request.json
        
        from ..features.template_engine import TemplateEngine
        
        engine = TemplateEngine(html_content=data.get('html', ''))
        preview = engine.preview(
            recipient=data.get('recipient', 'test@example.com'),
            extra_placeholders=data.get('placeholders', {})
        )
        
        return jsonify({
            'html': preview,
            'placeholders': engine.get_used_placeholders()
        })
    
    @app.route('/api/logs/success')
    @api_key_or_login_required
    @limiter.limit("30/minute")
    def api_success_logs():
        """Get success logs."""
        log_path = 'logs/success-emails.txt'
        if os.path.exists(log_path):
            with open(log_path, 'r') as f:
                emails = [line.strip() for line in f if line.strip()]
            return jsonify({'emails': emails[-100:]})
        return jsonify({'emails': []})
    
    @app.route('/api/logs/failed')
    @api_key_or_login_required
    @limiter.limit("30/minute")
    def api_failed_logs():
        """Get failed logs."""
        log_path = 'logs/failed-emails.txt'
        if os.path.exists(log_path):
            with open(log_path, 'r') as f:
                lines = [line.strip() for line in f if line.strip()]
            return jsonify({'failures': lines[-100:]})
        return jsonify({'failures': []})
    
    @app.route('/api/stats')
    @api_key_or_login_required
    @limiter.limit("30/minute")
    def api_stats():
        """
        Get overall sending statistics.
        
        Requires:
            Authentication via API key or login session
            
        Rate Limit:
            30 requests per minute
            
        Returns:
            JSON object with aggregate statistics:
            {
                "total_sent": int,
                "total_failed": int,
                "total_attempts": int,
                "success_rate": float (percentage)
            }
        """
        success_count = 0
        failed_count = 0
        
        if os.path.exists('logs/success-emails.txt'):
            with open('logs/success-emails.txt', 'r') as f:
                success_count = sum(1 for line in f if line.strip())
        
        if os.path.exists('logs/failed-emails.txt'):
            with open('logs/failed-emails.txt', 'r') as f:
                failed_count = sum(1 for line in f if line.strip())
        
        total = success_count + failed_count
        success_rate = round(success_count / total * 100, 2) if total > 0 else 0
        
        return jsonify({
            'total_sent': success_count,
            'total_failed': failed_count,
            'total_attempts': total,
            'success_rate': success_rate
        })
    
    @app.route('/api/webhooks', methods=['GET'])
    @api_key_or_login_required
    @limiter.limit("30/minute")
    def api_list_webhooks():
        """List registered webhooks."""
        from ..services.webhook_service import WebhookService
        
        service = WebhookService()
        webhooks = service.get_webhooks()
        
        return jsonify({
            'webhooks': [w.to_dict() for w in webhooks]
        })
    
    @app.route('/api/webhooks', methods=['POST'])
    @api_key_or_login_required
    @limiter.limit("10/minute")
    def api_register_webhook():
        """Register new webhook."""
        data = request.json
        
        if not data.get('url'):
            return jsonify({'error': 'Webhook URL required'}), 400
        
        from ..services.webhook_service import WebhookService, WebhookEvent
        
        service = WebhookService()
        
        # Parse events
        events = None
        if data.get('events'):
            events = []
            for e in data['events']:
                try:
                    events.append(WebhookEvent(e))
                except ValueError:
                    pass
        
        webhook = service.register_webhook(
            url=data['url'],
            events=events,
            secret=data.get('secret')
        )
        
        return jsonify({
            'success': True,
            'webhook': webhook.to_dict()
        })


def register_tracking_routes(app: Flask):
    """
    Register email tracking routes.
    
    Endpoints:
        - /track/open/<email_id>: Tracking pixel for open detection
        - /track/click/<email_id>: Link click tracking with redirect
        - /track/unsubscribe/<email_id>: Unsubscribe handling
    """
    
    @app.route('/track/open/<email_id>')
    def track_open(email_id):
        """
        Track email open via 1x1 transparent pixel.
        
        Args:
            email_id: Unique email identifier for tracking
            
        Returns:
            1x1 transparent GIF image with no-cache headers
            
        Notes:
            - Records open event with IP and user agent
            - Returns valid image regardless of tracking success
        """
        from ..services.tracking_service import TrackingService, TRACKING_PIXEL_GIF
        
        service = TrackingService()
        service.record_event(
            email_id=email_id,
            event_type='open',
            recipient='',  # Would be looked up from email_id
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string
        )
        
        return TRACKING_PIXEL_GIF, 200, {
            'Content-Type': 'image/gif',
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'Pragma': 'no-cache',
            'Expires': '0'
        }
    
    @app.route('/track/click/<email_id>')
    def track_click(email_id):
        """
        Track link click and redirect to destination.
        
        Args:
            email_id: Unique email identifier for tracking
            
        Query Parameters:
            url: Destination URL to redirect to
            lid: Optional link identifier for A/B testing
            
        Returns:
            302 Redirect to the destination URL
            
        Notes:
            - Records click event with IP, user agent, and clicked URL
            - Redirects to '/' if no URL provided
        """
        from ..services.tracking_service import TrackingService
        
        url = request.args.get('url', '/')
        link_id = request.args.get('lid')
        
        service = TrackingService()
        service.record_event(
            email_id=email_id,
            event_type='click',
            recipient='',
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string,
            url=url,
            metadata={'link_id': link_id}
        )
        
        return redirect(url)
    
    @app.route('/track/unsubscribe/<email_id>')
    def track_unsubscribe(email_id):
        """
        Handle unsubscribe request with secure token validation.
        
        Args:
            email_id: Unique email identifier from the tracking system
            
        Query Parameters:
            token: Secure HMAC-signed token for validation
            
        Returns:
            Unsubscribe confirmation page or error message
        """
        from ..services.bounce_service import BounceService
        from ..services.tracking_service import TrackingService
        
        token = request.args.get('token')
        
        # Validate the unsubscribe token
        is_valid, error_message = validate_unsubscribe_token(
            token=token,
            email_id=email_id
        )
        
        if not is_valid:
            logger.warning(
                f"Invalid unsubscribe attempt for email_id={email_id}: {error_message}"
            )
            return jsonify({
                'error': 'Invalid or expired unsubscribe link',
                'message': 'Please use the unsubscribe link from your email or contact support.'
            }), 400
        
        # Look up email from tracking service
        tracking_service = TrackingService()
        email = tracking_service.get_email_by_id(email_id)
        
        if not email:
            logger.warning(f"Unsubscribe: email_id not found: {email_id}")
            # Still process unsubscribe to avoid information leakage
            email = ''
        
        # Process the unsubscribe
        service = BounceService()
        service.process_unsubscribe(
            email=email,
            campaign_id=None
        )
        
        # Record the tracking event
        tracking_service.record_event(
            email_id=email_id,
            event_type='unsubscribe',
            recipient=email,
            ip_address=request.remote_addr,
            user_agent=request.user_agent.string
        )
        
        # Return success page
        return render_template('unsubscribed.html') if os.path.exists(
            'src/unified_sender/web/templates/unsubscribed.html'
        ) else "You have been unsubscribed successfully."


def register_health_routes(app: Flask):
    """
    Register health check and monitoring endpoints.
    
    Endpoints:
        - /health: Basic health check (public)
        - /health/detailed: Detailed component health (authenticated)
        - /ready: Kubernetes readiness probe
        - /live: Kubernetes liveness probe
    """
    
    @app.route('/health')
    def health_check():
        """
        Basic health check endpoint.
        
        Public endpoint that returns application health status.
        Suitable for load balancer health checks.
        
        Returns:
            200: Application is healthy
            {
                "status": "healthy",
                "timestamp": ISO 8601 timestamp
            }
        """
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.now(UTC).isoformat()
        })
    
    @app.route('/health/detailed')
    @api_key_or_login_required
    def health_check_detailed():
        """
        Detailed health check with component status.
        
        Requires:
            Authentication via API key or login session
            
        Returns:
            200: All components healthy or degraded status
            {
                "status": "healthy" | "degraded",
                "timestamp": ISO 8601 timestamp,
                "components": {
                    "database": { "status": str, ... },
                    "smtp": { "status": str, "active_servers": int },
                    "disk": { "status": str, "free_gb": float }
                }
            }
        """
        from ..data.database import get_engine
        
        status = {
            'status': 'healthy',
            'timestamp': datetime.now(UTC).isoformat(),
            'components': {}
        }
        
        # Check database
        try:
            engine = get_engine()
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            status['components']['database'] = {
                'status': 'healthy',
                'type': 'sqlite'
            }
        except Exception as e:
            status['components']['database'] = {
                'status': 'unhealthy',
                'error': str(e)
            }
            status['status'] = 'degraded'
        
        # Check SMTP servers
        try:
            from ..data.database import get_session_direct
            from ..data.repositories import SMTPRepository
            
            session = get_session_direct()
            try:
                repo = SMTPRepository(session)
                servers = repo.get_active()
                status['components']['smtp'] = {
                    'status': 'healthy',
                    'active_servers': len(servers)
                }
            finally:
                session.close()
        except Exception as e:
            status['components']['smtp'] = {
                'status': 'unknown',
                'error': str(e)
            }
        
        # Check disk space for logs
        try:
            import shutil
            total, used, free = shutil.disk_usage('.')
            free_gb = free / (1024 ** 3)
            status['components']['disk'] = {
                'status': 'healthy' if free_gb > 1 else 'warning',
                'free_gb': round(free_gb, 2)
            }
        except Exception as e:
            status['components']['disk'] = {
                'status': 'unknown',
                'error': str(e)
            }
        
        return jsonify(status)
    
    @app.route('/ready')
    def readiness_check():
        """
        Kubernetes readiness probe.
        
        Checks if the application is ready to handle traffic.
        Returns 200 if database connection is available.
        
        Returns:
            200: Application ready to handle requests
            503: Application not ready (database unavailable)
        """
        # Check if app can handle requests
        try:
            from ..data.database import get_engine
            engine = get_engine()
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return jsonify({'ready': True}), 200
        except Exception:
            return jsonify({'ready': False}), 503
    
    @app.route('/live')
    def liveness_check():
        """
        Kubernetes liveness probe.
        
        Checks if the application process is alive and responding.
        Always returns 200 if the application is running.
        
        Returns:
            200: Application is alive
            {"alive": true}
        """
        return jsonify({'alive': True}), 200


def register_socketio_events(sio: SocketIO):
    """Register WebSocket events."""
    
    @sio.on('connect')
    def handle_connect():
        """Handle client connection."""
        if not current_user.is_authenticated:
            return False  # Reject unauthenticated connections
        
        emit('connected', {'status': 'connected'})
        logger.info(f"Client connected via WebSocket: {current_user.username}")
    
    @sio.on('disconnect')
    def handle_disconnect():
        """Handle client disconnection."""
        logger.info("Client disconnected")
    
    @sio.on('start_campaign')
    def handle_start_campaign(data):
        """Start campaign via WebSocket."""
        if not current_user.is_authenticated:
            return
        
        campaign_id = data.get('campaign_id')
        
        emit('campaign_started', {
            'campaign_id': campaign_id,
            'status': 'started',
            'timestamp': datetime.now(UTC).isoformat()
        })
        
        logger.info(f"Campaign {campaign_id} started via WebSocket by {current_user.username}")
    
    @sio.on('pause_campaign')
    def handle_pause_campaign(data):
        """Pause campaign."""
        if not current_user.is_authenticated:
            return
        
        campaign_id = data.get('campaign_id')
        
        emit('campaign_paused', {
            'campaign_id': campaign_id,
            'status': 'paused',
            'timestamp': datetime.now(UTC).isoformat()
        })
    
    @sio.on('resume_campaign')
    def handle_resume_campaign(data):
        """Resume campaign."""
        if not current_user.is_authenticated:
            return
        
        campaign_id = data.get('campaign_id')
        
        emit('campaign_resumed', {
            'campaign_id': campaign_id,
            'status': 'resumed',
            'timestamp': datetime.now(UTC).isoformat()
        })
    
    @sio.on('stop_campaign')
    def handle_stop_campaign(data):
        """Stop campaign."""
        if not current_user.is_authenticated:
            return
        
        campaign_id = data.get('campaign_id')
        
        emit('campaign_stopped', {
            'campaign_id': campaign_id,
            'status': 'stopped',
            'timestamp': datetime.now(UTC).isoformat()
        })


def emit_progress(data):
    """Emit progress update to connected clients."""
    ctx = get_app_context()
    ctx.emit_progress(data)


def emit_complete(data):
    """Emit campaign complete event."""
    ctx = get_app_context()
    ctx.emit_complete(data)

"""Main application factory."""

import os
import logging
from typing import Optional
from flask import Flask
from flask_login import LoginManager

from ..app_context import AppContext, get_app_context, set_app_context
from ..utils.logging_config import configure_logging
from ..data.database import init_db, get_session_direct
from ..data.models import User
from ..security.auth import get_user_by_id, hash_password
from ..data.repositories import UserRepository

# Import extensions (limiter, socketio)
from .extensions import limiter, socketio
from .events import register_socketio_events

# Import routes
from .routes.auth import auth_bp
from .routes.api import api_bp
from .routes.views import views_bp
from .routes.tracking import tracking_bp
from .routes.health import health_bp
from .routes.tools import tools_bp

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
    # Initialize logging
    configure_logging()
    
    app = Flask(__name__)
    
    # Configuration
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-prod')
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload
    
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
    # This logic calls init_app on limiter and socketio
    ctx.initialize(app)
    
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
    
    # Register SocketIO events
    register_socketio_events(socketio)
    
    # Initialize Database
    with app.app_context():
        try:
            init_db()
            
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
                    admin.password_hash = hash_password("admin")
                    session.add(admin)
                    session.commit()
                    logger.info("Created default user: admin / admin")
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

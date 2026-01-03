"""Application context and dependency injection container.

This module provides a centralized way to manage application dependencies,
replacing global state with explicit dependency injection.
"""

import os
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from flask import Flask
from flask_socketio import SocketIO
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import current_user

logger = logging.getLogger(__name__)


@dataclass
class AppContext:
    """
    Application context container for dependency injection.
    
    This replaces global state by providing a centralized container
    for all application dependencies.
    """
    
    # Flask extensions (initialized during app creation)
    socketio: Optional[SocketIO] = None
    limiter: Optional[Limiter] = None
    
    # Configuration
    config: Dict[str, Any] = field(default_factory=dict)
    
    # Flags
    is_initialized: bool = False
    
    def initialize(self, app: Flask) -> None:
        """
        Initialize all dependencies with the Flask app.
        
        Args:
            app: Flask application instance
        """
        if self.is_initialized:
            logger.warning("AppContext already initialized")
            return
        
        # Import extensions here to avoid circular imports
        from .web.extensions import limiter, socketio
        
        # Initialize rate limiter
        limiter.init_app(app)
        self.limiter = limiter
        
        # Initialize SocketIO
        socketio.init_app(app)
        self.socketio = socketio
        
        self.is_initialized = True
        logger.info("AppContext initialized successfully")
    
    
    def emit_progress(self, data: Dict[str, Any]) -> None:
        """Emit progress update to connected clients."""
        if self.socketio:
            self.socketio.emit('campaign_progress', data)
    
    def emit_complete(self, data: Dict[str, Any]) -> None:
        """Emit campaign complete event."""
        if self.socketio:
            self.socketio.emit('campaign_complete', data)
    
    def emit_event(self, event: str, data: Dict[str, Any]) -> None:
        """Emit a generic event to connected clients."""
        if self.socketio:
            self.socketio.emit(event, data)
    
    def get_limiter(self) -> Optional[Limiter]:
        """Get the rate limiter instance."""
        return self.limiter
    
    def get_socketio(self) -> Optional[SocketIO]:
        """Get the SocketIO instance."""
        return self.socketio


# Default application context instance
# This can be replaced with a custom instance for testing
_app_context: Optional[AppContext] = None


def get_app_context() -> AppContext:
    """
    Get the application context singleton.
    
    Returns:
        AppContext instance
    """
    global _app_context
    if _app_context is None:
        _app_context = AppContext()
    return _app_context


def set_app_context(context: AppContext) -> None:
    """
    Set a custom application context (useful for testing).
    
    Args:
        context: AppContext instance to use
    """
    global _app_context
    _app_context = context


def reset_app_context() -> None:
    """Reset the application context to None (useful for testing)."""
    global _app_context
    _app_context = None


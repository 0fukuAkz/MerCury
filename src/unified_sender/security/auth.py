"""Authentication module with Flask-Login support."""

import os
import hashlib
import hmac
import secrets
import logging
import base64
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, UTC, timedelta
from dataclasses import dataclass, field

from flask import Flask, current_app
from flask_login import LoginManager, UserMixin

logger = logging.getLogger(__name__)

# Flask-Login manager
login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'info'


class User(UserMixin):
    """
    User wrapper for Flask-Login compatibility.
    
    This wraps the database User model to provide Flask-Login compatibility
    while using database-backed storage.
    """
    
    def __init__(
        self,
        id: str,
        username: str,
        password_hash: str,
        email: str = "",
        is_admin: bool = False,
        is_active: bool = True,
        created_at: Optional[datetime] = None,
        last_login: Optional[datetime] = None,
        must_change_password: bool = False
    ):
        self.id = id
        self.username = username
        self.password_hash = password_hash
        self.email = email
        self._is_admin = is_admin
        self._is_active = is_active
        self.created_at = created_at or datetime.now(UTC)
        self.last_login = last_login
        self.must_change_password = must_change_password
    
    @property
    def is_admin(self) -> bool:
        """Check if user is admin."""
        return self._is_admin
    
    @property
    def is_active(self) -> bool:
        """Check if user is active (required by Flask-Login)."""
        return self._is_active
    
    def get_id(self) -> str:
        """Return unique identifier for Flask-Login."""
        return str(self.id)
    
    def check_password(self, password: str) -> bool:
        """Verify password against hash."""
        return verify_password(password, self.password_hash)
    
    def set_password(self, password: str) -> None:
        """Set new password hash."""
        self.password_hash = hash_password(password)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'is_admin': self.is_admin,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None,
            'must_change_password': self.must_change_password
        }
    
    @classmethod
    def from_db_model(cls, db_user) -> 'User':
        """Create User wrapper from database model."""
        return cls(
            id=str(db_user.id),
            username=db_user.username,
            password_hash=db_user.password_hash,
            email=db_user.email or "",
            is_admin=db_user.is_admin,
            is_active=db_user.is_active,
            created_at=db_user.created_at,
            last_login=db_user.last_login_at,
            must_change_password=db_user.must_change_password
        )


def hash_password(password: str, salt: Optional[bytes] = None) -> str:
    """
    Hash password using PBKDF2-SHA256.
    
    Args:
        password: Plain text password
        salt: Optional salt (generated if not provided)
        
    Returns:
        Hash string in format: salt$hash
    """
    if salt is None:
        salt = secrets.token_bytes(32)
    
    # Use PBKDF2 with SHA256
    hash_bytes = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode(),
        salt,
        iterations=480000
    )
    
    # Store as salt$hash (both base64 encoded)
    import base64
    salt_b64 = base64.b64encode(salt).decode()
    hash_b64 = base64.b64encode(hash_bytes).decode()
    
    return f"{salt_b64}${hash_b64}"


def verify_password(password: str, password_hash: str) -> bool:
    """
    Verify password against hash.
    
    Args:
        password: Plain text password to verify
        password_hash: Stored hash in format salt$hash
        
    Returns:
        True if password matches
    """
    try:
        import base64
        
        parts = password_hash.split('$')
        if len(parts) != 2:
            return False
        
        salt = base64.b64decode(parts[0])
        stored_hash = base64.b64decode(parts[1])
        
        # Compute hash with same salt
        computed_hash = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode(),
            salt,
            iterations=480000
        )
        
        return secrets.compare_digest(computed_hash, stored_hash)
        
    except Exception as e:
        logger.error(f"Password verification error: {e}")
        return False


def create_user(
    username: str,
    password: str,
    email: str = "",
    is_admin: bool = False,
    must_change_password: bool = False
) -> User:
    """
    Create a new user in the database.
    
    Args:
        username: Unique username
        password: Plain text password (will be hashed)
        email: User email
        is_admin: Whether user has admin privileges
        must_change_password: Force password change on first login
        
    Returns:
        Created User object
    """
    from ..data.database import get_session_direct
    from ..data.repositories import UserRepository
    from ..data.models import User as DBUser
    
    password_hash = hash_password(password)
    
    session = get_session_direct()
    try:
        repo = UserRepository(session)
        
        # Check if username already exists
        if repo.username_exists(username):
            raise ValueError(f"Username already exists: {username}")
        
        # Create database user
        db_user = DBUser(
            username=username,
            password_hash=password_hash,
            email=email or None,
            is_admin=is_admin,
            is_active=True,
            must_change_password=must_change_password,
            password_changed_at=datetime.now(UTC)
        )
        
        db_user = repo.create(db_user)
        
        logger.info(f"Created user: {username}")
        
        return User.from_db_model(db_user)
        
    finally:
        session.close()


def get_user_by_id(user_id: str) -> Optional[User]:
    """Get user by ID from database."""
    from ..data.database import get_session_direct
    from ..data.repositories import UserRepository
    
    session = get_session_direct()
    try:
        repo = UserRepository(session)
        db_user = repo.get_by_id(int(user_id))
        
        if db_user:
            return User.from_db_model(db_user)
        return None
        
    except (ValueError, TypeError):
        return None
    finally:
        session.close()


def get_user_by_username(username: str) -> Optional[User]:
    """Get user by username from database."""
    from ..data.database import get_session_direct
    from ..data.repositories import UserRepository
    
    session = get_session_direct()
    try:
        repo = UserRepository(session)
        db_user = repo.get_by_username(username)
        
        if db_user:
            return User.from_db_model(db_user)
        return None
        
    finally:
        session.close()


def authenticate(username: str, password: str) -> Optional[User]:
    """
    Authenticate user with username and password.
    
    Args:
        username: Username
        password: Plain text password
        
    Returns:
        User object if authentication succeeds, None otherwise
    """
    from ..data.database import get_session_direct
    from ..data.repositories import UserRepository
    
    session = get_session_direct()
    try:
        repo = UserRepository(session)
        db_user = repo.get_by_username(username)
        
        if db_user is None:
            # Fix: Timing attack mitigation
            # Perform dummy hash verification to simulate load
            dummy_salt = secrets.token_bytes(32)
            dummy_hash = hash_password('dummy', dummy_salt)
            verify_password(password, dummy_hash)
            
            logger.warning(f"Authentication failed: Invalid credentials for: {username}")
            return None
        
        if not db_user.is_active:
            # We still return fast here as user enumeration for DISABLED users is less critical
            # but arguably should be constant time too. 
            # For now, prioritizing invalid user/password.
            logger.warning(f"Authentication failed: User disabled: {username}")
            return None
        
        if not verify_password(password, db_user.password_hash):
            logger.warning(f"Authentication failed: Invalid credentials for: {username}")
            return None
        
        # Update last login
        db_user.last_login_at = datetime.now(UTC)
        db_user.login_count = (db_user.login_count or 0) + 1
        session.commit()
        
        logger.info(f"User authenticated: {username}")
        
        return User.from_db_model(db_user)
        
    finally:
        session.close()


@login_manager.user_loader
def load_user(user_id: str) -> Optional[User]:
    """Flask-Login user loader callback."""
    return get_user_by_id(user_id)


def init_auth(app: Flask) -> None:
    """
    Initialize authentication for Flask app.
    
    Creates default admin user if none exists in database.
    """
    from ..data.database import get_session_direct, init_db
    from ..data.repositories import UserRepository
    
    login_manager.init_app(app)
    
    # Ensure database tables exist
    init_db()
    
    session = get_session_direct()
    try:
        repo = UserRepository(session)
        
        # Create default admin user if none exists
        # Create default admin user ONLY if explicitly configured
        admins = repo.get_admins()
        if not admins:
            default_username = os.environ.get('ADMIN_USERNAME')
            default_password = os.environ.get('ADMIN_PASSWORD')
            default_email = os.environ.get('ADMIN_EMAIL', 'admin@localhost')
            
            if default_username and default_password:
                create_user(
                    username=default_username,
                    password=default_password,
                    email=default_email,
                    is_admin=True,
                    must_change_password=True
                )
                logger.info(f"Created initial admin user: {default_username}")
            else:
                logger.warning(
                    "No admin user found and ADMIN_USERNAME/ADMIN_PASSWORD not set. "
                    "Web UI will be inaccessible until an admin is created."
                )
    finally:
        session.close()


def require_api_key(api_key: str) -> bool:
    """
    Validate API key for programmatic access.
    
    Args:
        api_key: API key to validate
        
    Returns:
        True if valid
        
    Security:
        API keys must be explicitly configured via API_KEYS environment variable.
        No fallback to debug mode - this prevents accidental security bypasses in production.
    """
    if not api_key:
        return False
    
    import shlex
    try:
        # Use shlex to handle quoted keys or spaces correctly
        env_val = os.environ.get('API_KEYS', '')
        if ',' in env_val:
            # Legacy simple split
            valid_keys = [k.strip() for k in env_val.split(',') if k.strip()]
        else:
            # Handle potential shell-style quoting
            valid_keys = shlex.split(env_val)
    except Exception:
         # Fallback
         valid_keys = []
    
    if not valid_keys:
        # No API keys configured - reject all requests
        # This is secure by default - admin must explicitly configure API keys
        logger.warning(
            "API key authentication attempted but no API_KEYS configured. "
            "Set API_KEYS environment variable to enable API access."
        )
        return False
    
    # Use constant-time comparison to prevent timing attacks
    return any(secrets.compare_digest(api_key, valid_key) for valid_key in valid_keys)


# =============================================================================
# Secure Token Generation/Validation for Unsubscribe Links
# =============================================================================

def _get_unsubscribe_secret() -> bytes:
    """
    Get the secret key for unsubscribe token generation.
    
    Uses UNSUBSCRIBE_SECRET env var, falls back to SECRET_KEY, 
    or generates a random key (not recommended for production).
    """
    secret = os.environ.get('UNSUBSCRIBE_SECRET') or os.environ.get('SECRET_KEY')
    
    if not secret:
        logger.warning(
            "No UNSUBSCRIBE_SECRET or SECRET_KEY configured. "
            "Unsubscribe tokens will not persist across restarts. "
            "Set UNSUBSCRIBE_SECRET environment variable for production."
        )
        # Generate a random secret - tokens won't survive restarts
        if not hasattr(_get_unsubscribe_secret, '_fallback_secret'):
            _get_unsubscribe_secret._fallback_secret = secrets.token_hex(32)
        secret = _get_unsubscribe_secret._fallback_secret
    
    return secret.encode('utf-8')


def generate_unsubscribe_token(
    email: str,
    email_id: str,
    expires_days: int = 365
) -> str:
    """
    Generate a secure unsubscribe token.
    
    The token contains:
    - email address (hashed for privacy)
    - email_id for tracking
    - expiration timestamp
    - HMAC signature for verification
    
    Args:
        email: Email address to unsubscribe
        email_id: Unique email identifier
        expires_days: Token validity period in days
        
    Returns:
        URL-safe base64-encoded token
    """
    secret = _get_unsubscribe_secret()
    
    # Calculate expiration timestamp
    expires_at = datetime.now(UTC) + timedelta(days=expires_days)
    expires_ts = int(expires_at.timestamp())
    
    # Create token payload: email_id|email_hash|expires_ts
    email_hash = hashlib.sha256(email.lower().encode()).hexdigest()[:16]
    payload = f"{email_id}|{email_hash}|{expires_ts}"
    
    # Generate HMAC signature
    signature = hmac.new(
        secret,
        payload.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()[:32]
    
    # Combine payload and signature
    token_data = f"{payload}|{signature}"
    
    # Encode as URL-safe base64
    token = base64.urlsafe_b64encode(token_data.encode('utf-8')).decode('utf-8')
    
    return token


def validate_unsubscribe_token(
    token: str,
    email_id: str,
    email: Optional[str] = None
) -> Tuple[bool, str]:
    """
    Validate an unsubscribe token.
    
    Args:
        token: The token to validate
        email_id: Expected email_id (from URL)
        email: Optional email to verify (if known)
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not token:
        return False, "Missing token"
    
    try:
        # Decode token
        token_data = base64.urlsafe_b64decode(token.encode('utf-8')).decode('utf-8')
        parts = token_data.split('|')
        
        if len(parts) != 4:
            return False, "Invalid token format"
        
        token_email_id, token_email_hash, expires_ts_str, signature = parts
        
        # Verify email_id matches
        if not secrets.compare_digest(token_email_id, email_id):
            logger.warning(f"Unsubscribe token email_id mismatch: {token_email_id} != {email_id}")
            return False, "Token does not match this email"
        
        # Check expiration
        try:
            expires_ts = int(expires_ts_str)
            if datetime.now(UTC).timestamp() > expires_ts:
                return False, "Token has expired"
        except ValueError:
            return False, "Invalid expiration timestamp"
        
        # Verify signature
        secret = _get_unsubscribe_secret()
        payload = f"{token_email_id}|{token_email_hash}|{expires_ts_str}"
        expected_signature = hmac.new(
            secret,
            payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()[:32]
        
        if not secrets.compare_digest(signature, expected_signature):
            logger.warning(f"Unsubscribe token signature mismatch for email_id: {email_id}")
            return False, "Invalid token signature"
        
        # Optionally verify email hash
        if email:
            email_hash = hashlib.sha256(email.lower().encode()).hexdigest()[:16]
            if not secrets.compare_digest(token_email_hash, email_hash):
                logger.warning(f"Unsubscribe token email hash mismatch for email_id: {email_id}")
                return False, "Token does not match this email address"
        
        return True, ""
        
    except Exception as e:
        logger.error(f"Unsubscribe token validation error: {e}")
        return False, "Invalid token"


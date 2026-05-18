"""SMTP server model with encrypted password support."""

import logging
from enum import Enum
from sqlalchemy import Column, String, Integer, Boolean, Float, JSON
from sqlalchemy.orm import relationship

from ..database import Base
from .base import BaseModel

logger = logging.getLogger(__name__)


class SMTPServerStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    RATE_LIMITED = "rate_limited"
    ERROR = "error"


class SMTPServer(Base, BaseModel):
    """SMTP server configuration model with encrypted passwords."""
    
    __tablename__ = 'smtpservers'
    
    name = Column(String(100), nullable=False, unique=True)
    host = Column(String(255), nullable=False)
    port = Column(Integer, default=587)
    username = Column(String(255))
    _password = Column('password', String(500))  # Encrypted password storage
    
    # Connection settings.
    # `tls_mode` is the source of truth ('none' | 'starttls' | 'ssl');
    # use_tls / use_ssl are retained for back-compat and kept in sync by
    # the tls_mode setter below.
    tls_mode = Column(String(16), default='starttls')
    use_tls = Column(Boolean, default=True)
    use_ssl = Column(Boolean, default=False)
    use_auth = Column(Boolean, default=True)
    timeout = Column(Integer, default=30)
    
    # Sender defaults
    from_email = Column(String(255))
    from_name = Column(String(255))
    
    # Status and health
    status = Column(String(50), default=SMTPServerStatus.ACTIVE.value)
    is_enabled = Column(Boolean, default=True)
    
    # Rate limiting (per-process limits enforced in-memory by the engine;
    # only the *configured* maxima are persisted, not the live counters).
    max_per_hour = Column(Integer, default=500)
    max_per_minute = Column(Integer, default=30)
    
    # Load balancing
    weight = Column(Float, default=1.0)
    priority = Column(Integer, default=0)
    
    # Circuit breaker
    failure_count = Column(Integer, default=0)
    last_failure_at = Column(String(50))
    circuit_open = Column(Boolean, default=False)
    
    # Statistics
    total_sent = Column(Integer, default=0)
    total_failed = Column(Integer, default=0)
    
    # Metadata
    settings = Column(JSON, default=dict)
    
    # Relationships
    campaign_configs = relationship("CampaignSMTPConfig", back_populates="smtp_server")
    
    @property
    def password(self) -> str:
        """Get decrypted password.

        Falls back to the raw column value if decryption fails — this
        preserves access for legacy rows persisted before the encryption
        service was introduced. The failure is logged so operators can see
        when ciphertext is corrupted vs. when a row is genuinely plaintext.
        """
        if not self._password:
            return ""

        try:
            from ...security.encryption import get_encryption_service
            service = get_encryption_service()
            return service.decrypt_if_needed(self._password)
        except Exception as e:
            logger.warning(
                "Decrypt failed for SMTP server '%s' password; "
                "returning raw column value. Cause: %s",
                getattr(self, 'name', '<unknown>'), type(e).__name__,
            )
            return self._password

    @password.setter
    def password(self, value: str):
        """Set encrypted password.

        Raises if encryption fails. The previous behavior — storing
        plaintext on encryption failure — silently leaked secrets into
        the database. Better to fail the write loudly and let the API
        layer surface the error than to persist unencrypted credentials.
        """
        if not value:
            self._password = ""
            return

        try:
            from ...security.encryption import get_encryption_service
            service = get_encryption_service()
            self._password = service.encrypt(value)
        except Exception as e:
            logger.error(
                "Encrypt failed for SMTP server '%s' password — refusing "
                "to persist plaintext. Cause: %s",
                getattr(self, 'name', '<unknown>'), type(e).__name__,
            )
            raise RuntimeError(
                "SMTP password encryption failed; "
                "refusing to store plaintext. Check encryption service health."
            ) from e
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate percentage."""
        total = self.total_sent + self.total_failed
        if total == 0:
            return 100.0
        return round((self.total_sent / total) * 100, 2)
    
    @property
    def is_available(self) -> bool:
        """Check if server is available for sending."""
        return (
            self.is_enabled and 
            self.status == SMTPServerStatus.ACTIVE.value and
            not self.circuit_open
        )
    
    # ---- tls_mode helpers ---------------------------------------------------
    # The setter keeps use_tls/use_ssl in lockstep with tls_mode so any
    # legacy reader sees consistent values. The getter resolves to a
    # canonical mode even on rows that pre-date the migration (e.g.
    # if tls_mode somehow ends up None at runtime).
    _TLS_MODES = ('none', 'starttls', 'ssl')

    @property
    def effective_tls_mode(self) -> str:
        """Canonical TLS mode, falling back to the legacy bools if unset."""
        if self.tls_mode in self._TLS_MODES:
            return self.tls_mode
        if self.use_ssl:
            return 'ssl'
        if self.use_tls:
            return 'starttls'
        return 'none'

    def set_tls_mode(self, mode: str) -> None:
        """Set tls_mode and keep the legacy booleans in sync."""
        if mode not in self._TLS_MODES:
            raise ValueError(f"tls_mode must be one of {self._TLS_MODES}, got {mode!r}")
        self.tls_mode = mode
        self.use_tls = (mode == 'starttls')
        self.use_ssl = (mode == 'ssl')

    def get_connection_config(self) -> dict:
        """Get configuration dict for SMTP connection."""
        return {
            'name': self.name,
            'host': self.host,
            'port': self.port,
            'username': self.username,
            'password': self.password,
            'tls_mode': self.effective_tls_mode,
            'use_tls': self.use_tls,
            'use_ssl': self.use_ssl,
            'use_auth': self.use_auth,
            'timeout': self.timeout,
            'from_email': self.from_email,
            'from_name': self.from_name,
        }
    
    def to_dict(self) -> dict:
        """Convert to dictionary excluding sensitive fields."""
        result = super().to_dict()
        # Remove protected fields but expose whether a password is configured
        result.pop('password', None)
        result.pop('_password', None)
        result['has_password'] = bool(self._password)
        return result

    def __repr__(self):
        return f"<SMTPServer(id={self.id}, name='{self.name}', host='{self.host}')>"


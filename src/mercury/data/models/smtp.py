"""SMTP server model with encrypted password support."""

from enum import Enum
from sqlalchemy import Column, String, Integer, Boolean, Float, JSON
from sqlalchemy.orm import relationship

from ..database import Base
from .base import BaseModel


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
    
    # Connection settings
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
    
    # Rate limiting
    max_per_hour = Column(Integer, default=500)
    max_per_minute = Column(Integer, default=30)
    current_hour_count = Column(Integer, default=0)
    current_minute_count = Column(Integer, default=0)
    
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
        """Get decrypted password."""
        if not self._password:
            return ""
        
        try:
            from ...security.encryption import get_encryption_service
            service = get_encryption_service()
            return service.decrypt_if_needed(self._password)
        except Exception:
            # Return as-is if decryption fails (might be plaintext legacy)
            return self._password
    
    @password.setter
    def password(self, value: str):
        """Set encrypted password."""
        if not value:
            self._password = ""
            return
        
        try:
            from ...security.encryption import get_encryption_service
            service = get_encryption_service()
            self._password = service.encrypt(value)
        except Exception:
            # Store as-is if encryption fails
            self._password = value
    
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
    
    def get_connection_config(self) -> dict:
        """Get configuration dict for SMTP connection."""
        return {
            'name': self.name,
            'host': self.host,
            'port': self.port,
            'username': self.username,
            'password': self.password,
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


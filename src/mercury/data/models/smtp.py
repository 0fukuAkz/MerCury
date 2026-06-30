"""SMTP server model with encrypted password support."""

import logging
from enum import Enum
from typing import TYPE_CHECKING, Optional, Any
from sqlalchemy import String, Integer, Boolean, Float, JSON
from sqlalchemy.orm import Mapped, relationship, mapped_column

from ..database import Base
from .base import BaseModel

if TYPE_CHECKING:
    from .campaign import CampaignSMTPConfig

logger = logging.getLogger(__name__)


class SMTPServerStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    RATE_LIMITED = "rate_limited"
    ERROR = "error"


class SMTPServer(Base, BaseModel):
    """SMTP server configuration model with encrypted passwords."""

    __tablename__ = "smtpservers"

    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[Optional[int]] = mapped_column(Integer, default=587)
    username: Mapped[Optional[str]] = mapped_column(String(255))
    _password: Mapped[Optional[Any]] = mapped_column(
        "password", String(500)
    )  # Encrypted password storage

    # Connection settings. `tls_mode` is the single TLS field
    # ('none' | 'starttls' | 'ssl').
    tls_mode: Mapped[str] = mapped_column(String(16), default="starttls", nullable=False)
    use_auth: Mapped[Optional[bool]] = mapped_column(Boolean, default=True)
    timeout: Mapped[Optional[int]] = mapped_column(Integer, default=30)

    # Sender defaults
    from_email: Mapped[Optional[str]] = mapped_column(String(255))
    from_name: Mapped[Optional[str]] = mapped_column(String(255))

    # Status and health
    status: Mapped[Optional[str]] = mapped_column(String(50), default=SMTPServerStatus.ACTIVE.value)
    is_enabled: Mapped[Optional[bool]] = mapped_column(Boolean, default=True)

    # Rate limiting (per-process limits enforced in-memory by the engine;
    # only the *configured* maxima are persisted, not the live counters).
    max_per_hour: Mapped[Optional[int]] = mapped_column(Integer, default=500)
    max_per_minute: Mapped[Optional[int]] = mapped_column(Integer, default=30)

    # Load balancing
    weight: Mapped[Optional[float]] = mapped_column(Float, default=1.0)
    priority: Mapped[Optional[int]] = mapped_column(Integer, default=0)

    # Circuit breaker
    failure_count: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    last_failure_at: Mapped[Optional[str]] = mapped_column(String(50))
    circuit_open: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)

    # Statistics
    total_sent: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    total_failed: Mapped[Optional[int]] = mapped_column(Integer, default=0)

    # IP Warmup
    ip_warmup: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)

    # Metadata
    settings: Mapped[Optional[Any]] = mapped_column(JSON, default=dict)

    # Relationships
    campaign_configs: Mapped[list["CampaignSMTPConfig"]] = relationship(
        "CampaignSMTPConfig", back_populates="smtp_server"
    )

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
                getattr(self, "name", "<unknown>"),
                type(e).__name__,
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
                getattr(self, "name", "<unknown>"),
                type(e).__name__,
            )
            raise RuntimeError(
                "SMTP password encryption failed; "
                "refusing to store plaintext. Check encryption service health."
            ) from e

    @property
    def success_rate(self) -> float:
        """Calculate success rate percentage."""
        sent = self.total_sent or 0
        total = sent + (self.total_failed or 0)
        if total == 0:
            return 100.0
        return round((sent / total) * 100, 2)

    @property
    def is_available(self) -> bool:
        """Check if server is available for sending."""
        return bool(
            self.is_enabled
            and self.status == SMTPServerStatus.ACTIVE.value
            and not self.circuit_open
        )

    _TLS_MODES = ("none", "starttls", "ssl")

    def set_tls_mode(self, mode: str) -> None:
        """Validate and set tls_mode."""
        if mode not in self._TLS_MODES:
            raise ValueError(f"tls_mode must be one of {self._TLS_MODES}, got {mode!r}")
        self.tls_mode = mode

    def get_connection_config(self) -> dict:
        """Get configuration dict for SMTP connection."""
        return {
            "name": self.name,
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "password": self.password,
            "tls_mode": self.tls_mode or "starttls",
            "use_auth": self.use_auth,
            "timeout": self.timeout,
            "from_email": self.from_email,
            "from_name": self.from_name,
        }

    def to_dict(self) -> dict:
        """Convert to dictionary excluding sensitive fields."""
        result = super().to_dict()
        # Remove protected fields but expose whether a password is configured
        result.pop("password", None)
        result.pop("_password", None)
        result["has_password"] = bool(self._password)
        return result

    def __repr__(self):
        return f"<SMTPServer(id={self.id}, name='{self.name}', host='{self.host}')>"

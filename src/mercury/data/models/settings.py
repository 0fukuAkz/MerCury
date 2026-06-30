"""Global application settings model."""

from typing import Optional, Any
from sqlalchemy import Integer, Float, Boolean, String, JSON
from sqlalchemy.orm import Mapped, mapped_column
from ..database import Base
from .base import BaseModel


class GlobalSetting(Base, BaseModel):
    """Singleton table for global configuration."""

    __tablename__ = "global_settings"

    # We'll validly only have one row, ID=1

    # --- General Settings ---
    daily_limit: Mapped[int] = mapped_column(Integer, default=500, nullable=False)
    hourly_limit: Mapped[int] = mapped_column(Integer, default=50, nullable=False)

    # Delay (seconds)
    min_delay: Mapped[float] = mapped_column(Float, default=10.0, nullable=False)
    max_delay: Mapped[float] = mapped_column(Float, default=60.0, nullable=False)

    # Defaults
    default_reply_to: Mapped[Optional[str]] = mapped_column(String(255))

    # --- Advanced Settings ---
    max_retries: Mapped[Optional[int]] = mapped_column(Integer, default=3)
    retry_delay_base: Mapped[Optional[int]] = mapped_column(
        Integer, default=300
    )  # Base seconds for backoff

    smtp_timeout: Mapped[Optional[int]] = mapped_column(Integer, default=30)
    dns_timeout: Mapped[Optional[int]] = mapped_column(Integer, default=5)

    max_concurrency: Mapped[Optional[int]] = mapped_column(Integer, default=5)

    # Proxy Configuration
    proxy_enabled: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    proxy_list: Mapped[Optional[Any]] = mapped_column(
        JSON, default=list
    )  # List of strings ["http://...", ...]
    proxy_rotation_strategy: Mapped[Optional[str]] = mapped_column(
        String(50), default="round_robin"
    )

    # --- Defaults ---
    batch_size: Mapped[Optional[int]] = mapped_column(Integer, default=1000)
    default_sender_name: Mapped[Optional[str]] = mapped_column(String(255))
    default_test_email: Mapped[Optional[str]] = mapped_column(String(255))

    # --- Logging & Maintenance ---
    log_retention_days: Mapped[Optional[int]] = mapped_column(Integer, default=30)
    log_level: Mapped[Optional[str]] = mapped_column(String(20), default="INFO")

    # --- UI Preferences ---
    ui_theme: Mapped[Optional[str]] = mapped_column(String(20), default="dark")

    # --- Encoding & Obfuscation ---
    encode_attachments: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    encode_html_entities: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    encode_body_base64: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    encode_unicode_homoglyphs: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)
    obfuscate_links: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)

    def __repr__(self):
        return f"<GlobalSetting(id={self.id})>"

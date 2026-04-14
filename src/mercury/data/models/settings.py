"""Global application settings model."""

from sqlalchemy import Column, Integer, Float, Boolean, String, JSON
from ..database import Base
from .base import BaseModel

class GlobalSetting(Base, BaseModel):
    """Singleton table for global configuration."""
    
    __tablename__ = 'global_settings'
    
    # We'll validly only have one row, ID=1
    
    # --- General Settings ---
    daily_limit = Column(Integer, default=500, nullable=False)
    hourly_limit = Column(Integer, default=50, nullable=False)
    
    # Delay (seconds)
    min_delay = Column(Float, default=10.0, nullable=False)
    max_delay = Column(Float, default=60.0, nullable=False)
    
    # Defaults
    default_reply_to = Column(String(255))
    
    # --- Advanced Settings ---
    max_retries = Column(Integer, default=3)
    retry_delay_base = Column(Integer, default=300)  # Base seconds for backoff
    
    smtp_timeout = Column(Integer, default=30)
    dns_timeout = Column(Integer, default=5)
    
    max_concurrency = Column(Integer, default=5)
    
    # Proxy Configuration
    proxy_enabled = Column(Boolean, default=False)
    proxy_list = Column(JSON, default=list)  # List of strings ["http://...", ...]
    proxy_rotation_strategy = Column(String(50), default='round_robin')

    # --- Defaults ---
    batch_size = Column(Integer, default=1000)
    default_sender_name = Column(String(255))
    default_test_email = Column(String(255))
    
    # --- Logging & Maintenance ---
    log_retention_days = Column(Integer, default=30)
    log_level = Column(String(20), default="INFO")
    
    # --- UI Preferences ---
    ui_theme = Column(String(20), default="dark")

    def __repr__(self):
        return f"<GlobalSetting(id={self.id})>"

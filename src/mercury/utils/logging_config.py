"""Structured logging configuration using structlog."""

import os
import re
import sys
import logging
from typing import Any, Optional
from datetime import datetime, UTC

import structlog


class _SuppressEngineIOSocketShutdown(logging.Filter):
    """Drop ``python-engineio``'s harmless socket-cleanup chatter.

    When a SocketIO client upgrades transport from polling to
    websocket, the old polling FD is closed by one greenlet; the
    cleanup path then calls ``shutdown()`` on it and races into
    ``Errno 9: Bad file descriptor``. The SocketIO session is fine —
    the message is on a socket that's already gone, after the work
    is done — but it logs once per upgrade and once per abrupt
    disconnect (every tab refresh / navigate / close). On a busy
    dashboard, dozens per minute.

    Happens with every async backend (eventlet, gevent, threading),
    so we suppress globally rather than per-backend. Other
    ``engineio.server`` log entries (real protocol errors, auth
    rejections, etc.) still pass through.
    """

    _NOISE = re.compile(r"socket shutdown error.*Bad file descriptor")

    def filter(self, record: logging.LogRecord) -> bool:
        return not self._NOISE.search(record.getMessage())


# Apply at import time. Idempotent — logging.Filter instances added to
# the same logger are de-duped by identity, and we re-add a fresh
# instance each import, so worst case we have a tiny extra filter
# object in the chain. Doing it here (rather than inside
# configure_logging) means it's active even before configure_logging
# runs, which matters for early-boot engineio traffic.
logging.getLogger("engineio.server").addFilter(_SuppressEngineIOSocketShutdown())


def configure_logging(
    level: str = "INFO", json_output: bool = False, log_file: Optional[str] = None
) -> None:
    """
    Configure structured logging for the application.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        json_output: If True, output JSON format (for production)
        log_file: Optional file path for file logging
    """
    # Determine if we're in development or production
    is_development = os.environ.get("FLASK_DEBUG", "").lower() == "true"

    if json_output is None:
        json_output = not is_development

    # Silence noisy third-party loggers in non-debug mode
    if not is_development:
        for _noisy in ("engineio", "socketio", "werkzeug", "aiosmtplib", "asyncio"):
            logging.getLogger(_noisy).setLevel(logging.WARNING)

    # Configure structlog processors (shared between structlog and standard library)
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    # Determine the final rendering processor
    if json_output:
        renderer: Any = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    # 1. Configure structlog to route through the standard library formatter
    structlog.configure(
        processors=shared_processors
        + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # 2. Configure the standard library formatter to render all logs using structlog
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=shared_processors,
    )

    # 3. Apply formatter to root logger handlers
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(getattr(logging, level.upper()))

    # Add stdout handler
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    root_logger.addHandler(stream_handler)

    # Add file handler if specified
    if log_file:
        os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)


def get_logger(name: Optional[str] = None) -> structlog.stdlib.BoundLogger:
    """
    Get a structured logger instance.

    Args:
        name: Logger name (usually __name__)

    Returns:
        Configured structlog logger
    """
    return structlog.get_logger(name)


class EmailSendLogger:
    """
    Specialized logger for email sending operations.

    Provides structured logging with consistent fields for email operations.
    """

    def __init__(self, campaign_id: Optional[str] = None):
        self.logger = get_logger("email_sender")
        self.campaign_id = campaign_id

    def log_send_start(self, recipient: str, correlation_id: str, smtp_server: str) -> None:
        """Log email send start."""
        self.logger.info(
            "email_send_start",
            recipient=recipient,
            correlation_id=correlation_id,
            smtp_server=smtp_server,
            campaign_id=self.campaign_id,
        )

    def log_send_success(
        self, recipient: str, correlation_id: str, smtp_server: str, duration_ms: float
    ) -> None:
        """Log successful email send."""
        self.logger.info(
            "email_send_success",
            recipient=recipient,
            correlation_id=correlation_id,
            smtp_server=smtp_server,
            duration_ms=round(duration_ms, 2),
            campaign_id=self.campaign_id,
        )

    def log_send_failure(
        self,
        recipient: str,
        correlation_id: str,
        error: str,
        error_type: str,
        is_transient: bool,
        smtp_server: Optional[str] = None,
    ) -> None:
        """Log failed email send."""
        self.logger.error(
            "email_send_failure",
            recipient=recipient,
            correlation_id=correlation_id,
            error=error,
            error_type=error_type,
            is_transient=is_transient,
            smtp_server=smtp_server,
            campaign_id=self.campaign_id,
        )

    def log_retry_queued(
        self, recipient: str, correlation_id: str, attempt: int, next_retry_at: datetime
    ) -> None:
        """Log email queued for retry."""
        self.logger.info(
            "email_retry_queued",
            recipient=recipient,
            correlation_id=correlation_id,
            attempt=attempt,
            next_retry_at=next_retry_at.isoformat(),
            campaign_id=self.campaign_id,
        )

    def log_campaign_start(self, total_recipients: int, concurrency: int) -> None:
        """Log campaign start."""
        self.logger.info(
            "campaign_start",
            campaign_id=self.campaign_id,
            total_recipients=total_recipients,
            concurrency=concurrency,
            started_at=datetime.now(UTC).isoformat(),
        )

    def log_campaign_complete(
        self, total: int, success: int, failed: int, duration_seconds: float
    ) -> None:
        """Log campaign completion."""
        self.logger.info(
            "campaign_complete",
            campaign_id=self.campaign_id,
            total=total,
            success=success,
            failed=failed,
            success_rate=round(success / total * 100, 2) if total > 0 else 0,
            duration_seconds=round(duration_seconds, 2),
            emails_per_second=round(total / duration_seconds, 2) if duration_seconds > 0 else 0,
        )

    def log_rate_limit_hit(self, smtp_server: str, current_rate: int, max_rate: int) -> None:
        """Log rate limit hit."""
        self.logger.warning(
            "rate_limit_hit",
            smtp_server=smtp_server,
            current_rate=current_rate,
            max_rate=max_rate,
            campaign_id=self.campaign_id,
        )

    def log_circuit_breaker_opened(self, smtp_server: str, failure_count: int) -> None:
        """Log circuit breaker opened."""
        self.logger.warning(
            "circuit_breaker_opened",
            smtp_server=smtp_server,
            failure_count=failure_count,
            campaign_id=self.campaign_id,
        )

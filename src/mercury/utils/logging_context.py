"""Enhanced logging with structured context."""

import logging
import functools
from typing import Any, Dict, Optional, Callable
from datetime import datetime, UTC
import json

# Use structlog if available, fallback to standard logging
try:
    import structlog

    _ = structlog  # optional dependency: used when STRUCTLOG_AVAILABLE is True
    STRUCTLOG_AVAILABLE = True
except ImportError:
    STRUCTLOG_AVAILABLE = False


class ContextLogger:
    """Logger with structured context."""

    def __init__(self, name: str, context: Optional[Dict[str, Any]] = None):
        """
        Initialize context logger.

        Args:
            name: Logger name
            context: Default context dict
        """
        self.logger = logging.getLogger(name)
        self.context = context or {}

    def _format_message(self, msg: str, extra_context: Optional[Dict[str, Any]] = None) -> str:
        """Format message with context."""
        full_context = {**self.context, **(extra_context or {})}

        if not full_context:
            return msg

        context_str = " | ".join(f"{k}={v}" for k, v in full_context.items())
        return f"{msg} | {context_str}"

    def debug(self, msg: str, **kwargs):
        """Log debug message with context."""
        formatted = self._format_message(msg, kwargs)
        self.logger.debug(formatted, extra=kwargs)

    def info(self, msg: str, **kwargs):
        """Log info message with context."""
        formatted = self._format_message(msg, kwargs)
        self.logger.info(formatted, extra=kwargs)

    def warning(self, msg: str, **kwargs):
        """Log warning message with context."""
        formatted = self._format_message(msg, kwargs)
        self.logger.warning(formatted, extra=kwargs)

    def error(self, msg: str, error: Optional[Exception] = None, **kwargs):
        """
        Log error message with context and exception details.

        Args:
            msg: Error message
            error: Exception object
            **kwargs: Additional context
        """
        if error:
            kwargs["error_type"] = error.__class__.__name__
            kwargs["error_msg"] = str(error)

            # Add exception attributes if available
            if hasattr(error, "details"):
                kwargs["error_details"] = getattr(error, "details")

        formatted = self._format_message(msg, kwargs)
        self.logger.error(formatted, extra=kwargs, exc_info=error is not None)

    def critical(self, msg: str, error: Optional[Exception] = None, **kwargs):
        """Log critical message with context."""
        if error:
            kwargs["error_type"] = error.__class__.__name__
            kwargs["error_msg"] = str(error)

        formatted = self._format_message(msg, kwargs)
        self.logger.critical(formatted, extra=kwargs, exc_info=error is not None)

    def with_context(self, **kwargs) -> "ContextLogger":
        """
        Create new logger with additional context.

        Args:
            **kwargs: Context to add

        Returns:
            New ContextLogger with merged context
        """
        new_context = {**self.context, **kwargs}
        return ContextLogger(self.logger.name, new_context)


def get_context_logger(name: str, **context) -> ContextLogger:
    """
    Get context logger.

    Args:
        name: Logger name
        **context: Initial context

    Returns:
        ContextLogger instance
    """
    return ContextLogger(name, context)


def log_email_operation(operation: str):
    """
    Decorator to log email operations with context.

    Args:
        operation: Operation name
    """

    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            logger = get_context_logger(func.__module__)

            # Extract context from kwargs
            context = {"operation": operation, "timestamp": datetime.now(UTC).isoformat()}

            if "recipient" in kwargs:
                context["recipient"] = kwargs["recipient"]
            if "correlation_id" in kwargs:
                context["correlation_id"] = kwargs["correlation_id"]

            logger.info(f"Starting {operation}", **context)

            try:
                result = await func(*args, **kwargs)
                logger.info(f"Completed {operation}", success=True, **context)
                return result
            except Exception as e:
                logger.error(f"Failed {operation}", error=e, **context)
                raise

        return wrapper

    return decorator


class EmailOperationContext:
    """Context manager for email operations."""

    def __init__(
        self,
        operation: str,
        recipient: Optional[str] = None,
        campaign_id: Optional[int] = None,
        correlation_id: Optional[str] = None,
    ):
        """
        Initialize operation context.

        Args:
            operation: Operation name
            recipient: Email recipient
            campaign_id: Campaign ID
            correlation_id: Correlation tracking ID
        """
        self.operation = operation
        self.context: Dict[str, Any] = {
            "operation": operation,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        if recipient:
            self.context["recipient"] = recipient
        if campaign_id:
            self.context["campaign_id"] = campaign_id
        if correlation_id:
            self.context["correlation_id"] = correlation_id

        self.logger = get_context_logger(__name__, **self.context)
        self.start_time = None

    def __enter__(self):
        """Enter context."""
        self.start_time = datetime.now(UTC)
        self.logger.info(f"▶️  Starting {self.operation}")
        return self.logger

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context."""
        duration = (datetime.now(UTC) - self.start_time).total_seconds()

        if exc_type is None:
            self.logger.info(f"✅ Completed {self.operation}", duration_seconds=duration)
        else:
            self.logger.error(
                f"❌ Failed {self.operation}", error=exc_val, duration_seconds=duration
            )

        return False  # Don't suppress exceptions


def log_error_with_context(
    logger: logging.Logger, msg: str, error: Exception, **context
) -> Dict[str, Any]:
    """
    Log error with full context and return structured data.

    Args:
        logger: Logger instance
        msg: Error message
        error: Exception
        **context: Additional context

    Returns:
        Structured error data
    """
    error_data = {
        "error_context_msg": msg,
        "error_type": error.__class__.__name__,
        "error_msg": str(error),
        "timestamp": datetime.now(UTC).isoformat(),
        **context,
    }

    # Add custom exception attributes
    if hasattr(error, "details"):
        error_data["error_details"] = getattr(error, "details")

    if hasattr(error, "is_transient"):
        error_data["is_transient"] = getattr(error, "is_transient")

    # Log with full context
    logger.error(f"{msg}: {error.__class__.__name__} - {error}", extra=error_data, exc_info=True)

    return error_data


def configure_structured_logging(
    log_level: str = "INFO", log_file: Optional[str] = None, json_logs: bool = False
):
    """
    Configure structured logging for the application.

    Args:
        log_level: Logging level
        log_file: Optional log file path
        json_logs: If True, output JSON format
    """
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)

        if json_logs:
            # JSON formatter for machine-readable logs
            formatter = logging.Formatter(
                json.dumps(
                    {
                        "timestamp": "%(asctime)s",
                        "level": "%(levelname)s",
                        "logger": "%(name)s",
                        "message": "%(message)s",
                    }
                )
            )
        else:
            formatter = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")

        file_handler.setFormatter(formatter)
        logging.getLogger().addHandler(file_handler)

    # Set levels for noisy loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("aiosmtplib").setLevel(logging.INFO)

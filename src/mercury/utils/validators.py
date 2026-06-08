"""Additional validation utilities."""

import logging
import re
from pathlib import Path

from ..exceptions import ValidationException, InvalidConfigValueError


def validate_file_path(path: str, must_exist: bool = True) -> Path:
    """
    Validate file path.

    Args:
        path: File path to validate
        must_exist: If True, file must exist

    Returns:
        Path object

    Raises:
        ValidationException: If path is invalid
    """
    if not path:
        raise ValidationException("File path cannot be empty")

    file_path = Path(path)

    if must_exist and not file_path.exists():
        raise ValidationException(f"File does not exist: {path}")

    if must_exist and not file_path.is_file():
        raise ValidationException(f"Path is not a file: {path}")

    return file_path


def validate_url(url: str, require_https: bool = False) -> str:
    """
    Validate URL format.

    Args:
        url: URL to validate
        require_https: If True, URL must use HTTPS

    Returns:
        Validated URL

    Raises:
        ValidationException: If URL is invalid
    """
    if not url:
        raise ValidationException("URL cannot be empty")

    # Basic URL pattern
    url_pattern = re.compile(
        r"^https?://"  # http:// or https://
        r"(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|"  # domain
        r"localhost|"  # localhost
        r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"  # IP
        r"(?::\d+)?"  # optional port
        r"(?:/?|[/?]\S+)$",
        re.IGNORECASE,
    )

    if not url_pattern.match(url):
        raise ValidationException(f"Invalid URL format: {url}")

    if require_https and not url.startswith("https://"):
        raise ValidationException(f"URL must use HTTPS: {url}")

    return url


def validate_port(port: int, allow_privileged: bool = False) -> int:
    """
    Validate network port number.

    Args:
        port: Port number
        allow_privileged: Allow ports < 1024

    Returns:
        Validated port

    Raises:
        InvalidConfigValueError: If port is invalid
    """
    if not isinstance(port, int):
        raise InvalidConfigValueError(f"Port must be an integer, got {type(port)}")

    if not allow_privileged and port < 1024:
        raise InvalidConfigValueError(f"Privileged port {port} not allowed (use 1024-65535)")

    if port < 1 or port > 65535:
        raise InvalidConfigValueError(f"Port {port} out of valid range (1-65535)")

    return port


def validate_positive_int(value: int, name: str = "value", min_value: int = 1) -> int:
    """
    Validate positive integer.

    Args:
        value: Value to validate
        name: Name of the value (for error messages)
        min_value: Minimum allowed value

    Returns:
        Validated value

    Raises:
        InvalidConfigValueError: If value is invalid
    """
    if not isinstance(value, int):
        raise InvalidConfigValueError(f"{name} must be an integer, got {type(value)}")

    if value < min_value:
        raise InvalidConfigValueError(f"{name} must be >= {min_value}, got {value}")

    return value


def validate_rate_limit(per_minute: int, per_hour: int) -> tuple[int, int]:
    """
    Validate rate limit configuration.

    Args:
        per_minute: Emails per minute
        per_hour: Emails per hour

    Returns:
        Tuple of (per_minute, per_hour)

    Raises:
        InvalidConfigValueError: If rate limits are invalid
    """
    if per_minute < 0:
        raise InvalidConfigValueError(f"per_minute must be >= 0, got {per_minute}")

    if per_hour < 0:
        raise InvalidConfigValueError(f"per_hour must be >= 0, got {per_hour}")

    # Check consistency
    if per_minute > 0 and per_hour > 0:
        if per_minute * 60 > per_hour:
            logger = logging.getLogger(__name__)
            logger.warning(
                f"per_minute ({per_minute}) * 60 = {per_minute * 60} exceeds per_hour ({per_hour}). "
                f"This may cause unexpected throttling."
            )

    return per_minute, per_hour


def validate_concurrency(concurrency: int, max_concurrency: int = 1000) -> int:
    """
    Validate concurrency setting.

    Args:
        concurrency: Concurrent operations
        max_concurrency: Maximum allowed concurrency

    Returns:
        Validated concurrency

    Raises:
        InvalidConfigValueError: If invalid
    """
    if concurrency < 1:
        raise InvalidConfigValueError(f"Concurrency must be >= 1, got {concurrency}")

    if concurrency > max_concurrency:
        raise InvalidConfigValueError(
            f"Concurrency {concurrency} exceeds maximum {max_concurrency}"
        )

    return concurrency

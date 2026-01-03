"""Engine layer - Async sender, connection pooling, rate limiting."""

from .async_sender import AsyncEmailSender, send_email_async, send_bulk_emails_async
from .connection_pool import SMTPConnectionPool, AsyncConnectionPool
from .rate_limiter import RateLimiter
from .retry_queue import RetryQueue

__all__ = [
    "AsyncEmailSender",
    "send_email_async",
    "send_bulk_emails_async",
    "SMTPConnectionPool",
    "AsyncConnectionPool",
    "RateLimiter",
    "RetryQueue",
]


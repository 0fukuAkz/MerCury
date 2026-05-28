"""Async email sender with full feature support."""

import asyncio
import logging
import mimetypes
import re
from typing import Optional, Dict, Any, List, Callable, Awaitable
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from datetime import datetime, UTC
from dataclasses import dataclass
import uuid

import aiosmtplib

from .connection_pool import SMTPConnectionPool, SMTPServerConfig, AsyncConnectionPool
from .rate_limiter import RateLimiter, RateLimiterConfig
from .retry_queue import RetryQueue
from ..features.placeholders import PlaceholderProcessor
from ..exceptions import (
    SMTPConnectionError,
    SMTPAuthenticationError,
    SMTPRateLimitError,
    SMTPMailboxError,
    TransientSMTPError,
    PermanentSMTPError
)

logger = logging.getLogger(__name__)


_LEADING_CODE_RE = re.compile(r'^\s*(\d{3})\b')


def _smtp_status_code(error: Exception) -> Optional[int]:
    """Extract a numeric SMTP status code, preferring the structured attribute.

    Order:
      1. aiosmtplib response exceptions expose ``code`` as an int.
      2. As a fallback, parse a leading 3-digit code from ``str(error)`` —
         covers raw exceptions like ``Exception("550 5.1.1 User unknown")``.
    Lower-level transport errors (TimeoutError, ConnectionError) have neither.
    """
    code = getattr(error, 'code', None)
    if isinstance(code, int) and 200 <= code < 600:
        return code
    match = _LEADING_CODE_RE.match(str(error))
    if match:
        parsed = int(match.group(1))
        if 200 <= parsed < 600:
            return parsed
    return None


def categorize_smtp_error(error: Exception) -> tuple[bool, str, Exception]:
    """
    Categorize SMTP errors and convert to custom exceptions.

    Strategy (in order):
      1. Class-based dispatch for transport errors and auth errors.
      2. Numeric SMTP status code (RFC 5321) when the server responded.
      3. Keyword heuristics on the exception text as a final fallback for
         drivers / proxies that surface non-standard error shapes.

    Args:
        error: Exception from SMTP operation

    Returns:
        Tuple of (is_transient, error_type, converted_exception)
    """
    err_msg = str(error)

    # 1. Transport-layer errors — never have an SMTP code.
    if isinstance(error, (aiosmtplib.SMTPServerDisconnected, ConnectionError, asyncio.TimeoutError)):
        return True, 'connection_error', SMTPConnectionError(err_msg, smtp_response=err_msg)

    # 2. Auth errors — always permanent regardless of code.
    if isinstance(error, aiosmtplib.SMTPAuthenticationError):
        return False, 'authentication_error', SMTPAuthenticationError(err_msg, smtp_response=err_msg)

    # 3. RFC 5321 status code dispatch.
    code = _smtp_status_code(error)
    if code is not None:
        # Specific buckets first; then 4xx = transient, 5xx = permanent.
        if code in (421, 450, 451, 452):
            return True, 'rate_limit', SMTPRateLimitError(err_msg, smtp_response=err_msg)
        if code in (550, 551, 553):
            return False, 'mailbox_error', SMTPMailboxError(err_msg, smtp_response=err_msg)
        if code in (552, 554):
            return False, 'permanent', PermanentSMTPError(err_msg, smtp_response=err_msg)
        if 400 <= code < 500:
            return True, 'transient', TransientSMTPError(err_msg, smtp_response=err_msg)
        if 500 <= code < 600:
            return False, 'permanent', PermanentSMTPError(err_msg, smtp_response=err_msg)

    # 4. Keyword heuristics (last resort, locale-fragile).
    #
    # Matched on \b-anchored regex instead of plain substring. The
    # previous ``'mailbox' in err_msg.lower()`` fired on recipient
    # addresses like ``mailbox-tester@example.com`` embedded in the
    # error text, mis-bucketing transient errors as permanent mailbox
    # failures and burying real recipients in the dead-letter log.
    # Multi-word phrases like 'rate limit' still match correctly because
    # \b anchors at the boundary between word and non-word chars on
    # either end of the phrase.
    error_str = err_msg.lower()

    def _hits(words: list[str]) -> bool:
        return any(re.search(rf'\b{re.escape(w)}\b', error_str) for w in words)

    if _hits(['rate limit', 'throttl', 'throttled', 'throttling', 'too many']):
        return True, 'rate_limit', SMTPRateLimitError(err_msg, smtp_response=err_msg)
    if _hits(['mailbox', 'does not exist', 'unknown user', 'no such']):
        return False, 'mailbox_error', SMTPMailboxError(err_msg, smtp_response=err_msg)
    if _hits(['timeout', 'temporarily', 'busy', 'try again', 'disconnect', 'disconnected']):
        return True, 'transient', TransientSMTPError(err_msg, smtp_response=err_msg)
    if _hits(['invalid', 'disabled', 'blocked', 'spam', 'blacklist', 'blacklisted']):
        return False, 'permanent', PermanentSMTPError(err_msg, smtp_response=err_msg)

    # 5. Default: transient (safer for retries on unknown errors).
    return True, 'unknown', TransientSMTPError(err_msg, smtp_response=err_msg)


@dataclass
class EmailResult:
    """Result of email send operation."""
    success: bool
    recipient: str
    correlation_id: Optional[str]
    timestamp: datetime
    smtp_server: Optional[str] = None
    smtp_response: Optional[str] = None
    error: Optional[str] = None
    error_type: Optional[str] = None
    is_transient: bool = False
    dry_run: bool = False
    
    def to_dict(self) -> dict:
        return {
            'success': self.success,
            'recipient': self.recipient,
            'correlation_id': self.correlation_id,
            'timestamp': self.timestamp.isoformat(),
            'smtp_server': self.smtp_server,
            'smtp_response': self.smtp_response,
            'error': self.error,
            'error_type': self.error_type,
            'is_transient': self.is_transient,
            'dry_run': self.dry_run
        }


@dataclass
class BulkSendResult:
    """Result of bulk send operation."""
    total: int
    success: int
    failed: int
    duration_seconds: float
    emails_per_second: float
    start_time: datetime
    end_time: datetime
    results: List[EmailResult]
    
    def to_dict(self) -> dict:
        return {
            'total': self.total,
            'success': self.success,
            'failed': self.failed,
            'duration_seconds': self.duration_seconds,
            'emails_per_second': self.emails_per_second,
            'start_time': self.start_time.isoformat(),
            'end_time': self.end_time.isoformat(),
            'success_rate': round(self.success / self.total * 100, 2) if self.total > 0 else 0
        }


class AsyncEmailSender:
    """High-performance async email sender."""
    
    def __init__(
        self,
        connection_pool: SMTPConnectionPool,
        rate_limiter: Optional[RateLimiter] = None,
        retry_queue: Optional[RetryQueue] = None,
        default_from_email: str = "",
        default_from_name: str = "",
        dry_run: bool = False
    ):
        """
        Initialize async email sender.
        
        Args:
            connection_pool: SMTP connection pool
            rate_limiter: Rate limiter instance
            retry_queue: Retry queue for failed sends
            default_from_email: Default sender email
            default_from_name: Default sender name
            dry_run: If True, don't actually send
        """
        self.connection_pool = connection_pool
        self.rate_limiter = rate_limiter
        self.retry_queue = retry_queue
        self.default_from_email = default_from_email
        self.default_from_name = default_from_name
        self.dry_run = dry_run
        
        # Statistics
        self.stats = {
            'total_sent': 0,
            'total_failed': 0,
            'total_retried': 0
        }
    
    async def send_email(
        self,
        recipient: str,
        subject: str,
        html_body: str,
        from_email: Optional[str] = None,
        from_name: Optional[str] = None,
        reply_to: Optional[str] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
        headers: Optional[Dict[str, str]] = None,
        correlation_id: Optional[str] = None,
        preferred_smtp: Optional[str] = None,
        force_base64_body: bool = False
    ) -> EmailResult:
        """
        Send single email asynchronously.
        
        Args:
            recipient: Email address to send to
            subject: Email subject line
            html_body: HTML email body
            from_email: Sender email address
            from_name: Sender name
            reply_to: Reply-to address
            attachments: List of attachment dicts
            headers: Additional email headers
            correlation_id: Tracking ID
            preferred_smtp: Preferred SMTP server name
            
        Returns:
            EmailResult with send status
        """
        correlation_id = correlation_id or str(uuid.uuid4())
        from_email = from_email or self.default_from_email
        from_name = from_name or self.default_from_name
        
        # Dry run mode — skip the SMTP send AND the pool acquire (preview
        # must work without real credentials), but still pace through the
        # rate limiter so the preview reflects the timing the real run
        # would have. Without this, --preview returns instantly even for
        # max_per_minute=20 configs, lying to operators about how long
        # the actual campaign will take.
        if self.dry_run:
            if self.rate_limiter:
                await self.rate_limiter.acquire(timeout=None)
            logger.info(f"[DRY-RUN] Would send to {recipient}: {subject}")
            return EmailResult(
                success=True,
                recipient=recipient,
                correlation_id=correlation_id,
                timestamp=datetime.now(UTC),
                dry_run=True
            )
        
        # Rate limiting
        if self.rate_limiter:
            rate_ok = await self.rate_limiter.acquire(timeout=30.0)
            if not rate_ok:
                return EmailResult(
                    success=False,
                    recipient=recipient,
                    correlation_id=correlation_id,
                    timestamp=datetime.now(UTC),
                    error="Rate limit exceeded",
                    error_type="rate_limit",
                    is_transient=True
                )
        
        # Initialize smtp_config to None before try block to avoid NameError in exception handler
        smtp_config = None
        
        try:
            # Build email message
            msg = EmailMessage()
            msg['Subject'] = subject
            msg['From'] = formataddr((from_name, from_email))
            msg['To'] = recipient
            msg['Date'] = formatdate(localtime=True)
            msg['Message-ID'] = make_msgid()
            msg['X-Correlation-ID'] = correlation_id
            
            if reply_to:
                msg['Reply-To'] = reply_to
            
            if headers:
                for key, value in headers.items():
                    msg[key] = value
            
            # Set content
            msg.set_content("This message requires HTML support.")
            html_cte = 'base64' if force_base64_body else None
            msg.add_alternative(html_body, subtype='html', cte=html_cte)
            
            # Add attachments
            if attachments:
                for attachment in attachments:
                    data = attachment['data']
                    filename = attachment['filename']
                    content_type = attachment.get('content_type')

                    if content_type:
                        maintype, subtype = content_type.split('/', 1)
                    else:
                        ctype, _ = mimetypes.guess_type(filename)
                        if ctype is None:
                            maintype, subtype = 'application', 'octet-stream'
                        else:
                            maintype, subtype = ctype.split('/', 1)

                    # Always pass bytes to add_attachment. Python's content
                    # manager dispatches on input type:
                    #   - bytes → set_bytes_content(msg, value, maintype,
                    #             subtype, ...) — accepts maintype kwarg.
                    #   - str   → set_text_content(msg, value, subtype, ...)
                    #             — does NOT accept maintype; passing it
                    #             raises TypeError on 3.12, or silently
                    #             drops the body on some 3.11 versions
                    #             (the cause of the "empty attachment" bug).
                    # Encoding str→bytes lets every content type take the
                    # bytes path uniformly.
                    if isinstance(data, str):
                        data = data.encode('utf-8')

                    msg.add_attachment(
                        data,
                        maintype=maintype,
                        subtype=subtype,
                        filename=filename
                    )
            
            # From-aware routing: when the caller didn't pin a specific
            # server and the resolved From address has a declared owner
            # in the pool, route through that owner. This prevents the
            # gateway-side 5.7.0 "From not in your addresses" reject that
            # O365/SES/SendGrid emit when the From: header doesn't match
            # the authenticated SMTP user's allowed-sender list.
            #
            # Falls back to the configured selection strategy when no
            # server declares ownership — preserves existing behavior for
            # the common single-From / single-server setup.
            routing_owner_name: Optional[str] = None
            if preferred_smtp is None and from_email:
                owner = self.connection_pool.select_server_for_from(from_email)
                if owner is not None:
                    preferred_smtp = owner.name
                    routing_owner_name = owner.name

            # Acquire connection and send
            conn, smtp_config = await self.connection_pool.acquire(
                preferred_server=preferred_smtp,
                timeout=30.0
            )

            # Per-send routing diagnostic. Lets operators correlate a
            # gateway-side reject ("From is not one of your addresses")
            # with which server the message actually went out on and
            # whether From-aware routing matched an owner. INFO level on
            # purpose — campaigns of meaningful size produce a lot of
            # these, but the only thing more painful than verbose logs
            # is debugging a 5.7.0 with no log of which server sent what.
            logger.info(
                "[route] recipient=%s from=%r server=%s owner_match=%s",
                recipient, from_email, smtp_config.name,
                'yes' if routing_owner_name == smtp_config.name
                else ('fallback' if from_email else 'no_from'),
            )
            
            try:
                result = await conn.send_message(msg)
                self.connection_pool.record_success(smtp_config)
                self.stats['total_sent'] += 1
                
                logger.info(f"✅ Sent to {recipient} via {smtp_config.name}")
                
                return EmailResult(
                    success=True,
                    recipient=recipient,
                    correlation_id=correlation_id,
                    timestamp=datetime.now(UTC),
                    smtp_server=smtp_config.name,
                    smtp_response=result.get('response')
                )
                
            finally:
                await self.connection_pool.release(conn, smtp_config)
                
        except (aiosmtplib.SMTPException, ConnectionError, asyncio.TimeoutError, OSError) as e:
            is_transient, error_type, converted_exc = categorize_smtp_error(e)
            
            # Record failure if we have a valid smtp_config
            if smtp_config is not None:
                self.connection_pool.record_failure(smtp_config, converted_exc)
            
            self.stats['total_failed'] += 1
            
            logger.error(
                f"❌ Failed to send to {recipient}: {error_type} - {e}",
                extra={'error_type': error_type, 'is_transient': is_transient}
            )
            
            # Add to retry queue if transient
            if is_transient and self.retry_queue:
                await self.retry_queue.add(
                    id=correlation_id,
                    data={
                        'recipient': recipient,
                        'subject': subject,
                        'html_body': html_body,
                        'from_email': from_email,
                        'from_name': from_name,
                        'reply_to': reply_to,
                        'attachments': attachments,
                        'headers': headers
                    },
                    error=str(converted_exc)
                )
                self.stats['total_retried'] += 1
                logger.info(f"🔄 Queued {recipient} for retry (attempt will be made later)")
            
            return EmailResult(
                success=False,
                recipient=recipient,
                correlation_id=correlation_id,
                timestamp=datetime.now(UTC),
                error=str(converted_exc),
                error_type=error_type,
                is_transient=is_transient
            )
    
    async def send_bulk(
        self,
        recipients: List[Dict[str, Any]],
        subject_template: str,
        html_template: str,
        from_email: Optional[str] = None,
        from_name: Optional[str] = None,
        concurrency: int = 50,
        progress_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None
    ) -> BulkSendResult:
        """
        Send bulk emails with controlled concurrency.
        
        Args:
            recipients: List of recipient dicts with email and placeholders
            subject_template: Subject line template with {{placeholders}}
            html_template: HTML template with {{placeholders}}
            from_email: Sender email
            from_name: Sender name
            concurrency: Maximum concurrent sends
            progress_callback: Async callback for progress updates
            
        Returns:
            BulkSendResult with statistics
        """
        semaphore = asyncio.Semaphore(concurrency)
        results: List[EmailResult] = []
        start_time = datetime.now(UTC)

        # Render through the project's PlaceholderProcessor — the single
        # source of truth for {{var}} semantics — instead of a naive
        # str.replace loop. This gives the convenience path the same
        # behavior as the web/service path: case/format-tolerant field
        # aliases ({{first_name}} matches a "First Name" column), the
        # 50+ built-in placeholders (date, domain, uuid, …), and unknown
        # placeholders left intact rather than partially mangled. One
        # processor instance for the whole batch; process() is pure given
        # its args, so it's safe to share across the concurrent sends.
        processor = PlaceholderProcessor()

        async def send_with_semaphore(
            recipient_data: Dict[str, Any],
            index: int
        ) -> EmailResult:
            async with semaphore:
                recipient_email = recipient_data.get('email')

                subject = processor.process(subject_template, recipient_data, {})
                body = processor.process(html_template, recipient_data, {})

                result = await self.send_email(
                    recipient=recipient_email,
                    subject=subject,
                    html_body=body,
                    from_email=from_email,
                    from_name=from_name
                )
                
                if progress_callback:
                    await progress_callback({
                        'index': index,
                        'total': len(recipients),
                        'recipient': recipient_email,
                        'success': result.success,
                        'percent': round((index + 1) / len(recipients) * 100, 1)
                    })
                
                return result
        
        # Send all emails concurrently
        tasks = [
            send_with_semaphore(r, i) 
            for i, r in enumerate(recipients)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results. Pair each return value with the original
        # recipient by index so an unexpected exception (one that escaped
        # send_email's own except block, e.g. a cancellation or a bug in
        # the placeholder substitution) still records the actual recipient
        # address. The previous ``recipient='unknown'`` made it impossible
        # to retry or even know who didn't get the email.
        processed_results = []
        for recipient_data, r in zip(recipients, results):
            if isinstance(r, EmailResult):
                processed_results.append(r)
            elif isinstance(r, Exception):
                processed_results.append(EmailResult(
                    success=False,
                    recipient=recipient_data.get('email', 'unknown'),
                    correlation_id=str(uuid.uuid4()),
                    timestamp=datetime.now(UTC),
                    error=str(r),
                    error_type='exception'
                ))
        
        end_time = datetime.now(UTC)
        duration = (end_time - start_time).total_seconds()
        success_count = sum(1 for r in processed_results if r.success)
        
        return BulkSendResult(
            total=len(recipients),
            success=success_count,
            failed=len(recipients) - success_count,
            duration_seconds=duration,
            emails_per_second=len(recipients) / duration if duration > 0 else 0,
            start_time=start_time,
            end_time=end_time,
            results=processed_results
        )
    
    def get_stats(self) -> Dict[str, Any]:
        """Get sender statistics."""
        return {
            **self.stats,
            'pool_status': self.connection_pool.get_status(),
            'retry_stats': self.retry_queue.get_stats() if self.retry_queue else None
        }


# Convenience functions

async def send_email_async(
    recipient: str,
    subject: str,
    html_body: str,
    smtp_config: Dict[str, Any],
    from_email: str,
    from_name: Optional[str] = None,
    reply_to: Optional[str] = None,
    attachments: Optional[List[Dict[str, Any]]] = None,
    headers: Optional[Dict[str, str]] = None,
    dry_run: bool = False
) -> Dict[str, Any]:
    """
    Send single email asynchronously (convenience function).
    
    This creates a temporary connection pool for one-off sends.
    For bulk sending, use AsyncEmailSender class directly.
    """
    config = SMTPServerConfig.from_dict(smtp_config)
    pool = AsyncConnectionPool(config, pool_size=1)
    
    try:
        await pool.initialize()
        conn = await pool.get_connection()
        
        if dry_run:
            logger.info(f"[DRY-RUN] Would send to {recipient}: {subject}")
            return {'success': True, 'dry_run': True}
        
        # Build message
        msg = EmailMessage()
        msg['Subject'] = subject
        msg['From'] = formataddr((from_name or from_email, from_email))
        msg['To'] = recipient
        msg['Date'] = formatdate(localtime=True)
        msg['Message-ID'] = make_msgid()
        
        if reply_to:
            msg['Reply-To'] = reply_to
        
        if headers:
            for key, value in headers.items():
                msg[key] = value
        
        msg.set_content("This message requires HTML support.")
        msg.add_alternative(html_body, subtype='html')
        
        if attachments:
            for att in attachments:
                ctype = att.get('content_type') or 'application/octet-stream'
                maintype, subtype = ctype.split('/', 1)
                data = att['data']
                # Always pass bytes — see note in send_email above. The str
                # path doesn't accept maintype as a kwarg and silently
                # produces empty MIME parts.
                if isinstance(data, str):
                    data = data.encode('utf-8')
                msg.add_attachment(
                    data,
                    maintype=maintype,
                    subtype=subtype,
                    filename=att['filename']
                )
        
        await conn.send_message(msg)
        
        logger.info(f"✅ Sent to {recipient}")
        return {
            'success': True,
            'recipient': recipient,
            'timestamp': datetime.now(UTC).isoformat()
        }
        
    except (aiosmtplib.SMTPException, ConnectionError, asyncio.TimeoutError, OSError) as e:
        is_transient, error_type, converted_exc = categorize_smtp_error(e)
        logger.error(f"❌ Failed to send to {recipient}: {error_type} - {e}")
        return {
            'success': False,
            'recipient': recipient,
            'error': str(converted_exc),
            'error_type': error_type,
            'is_transient': is_transient,
            'timestamp': datetime.now(UTC).isoformat()
        }
    finally:
        await pool.close_all()


async def send_bulk_emails_async(
    recipients: List[Dict[str, Any]],
    subject_template: str,
    html_template: str,
    smtp_config: Dict[str, Any],
    from_email: str,
    from_name: Optional[str] = None,
    concurrency: int = 50,
    progress_callback: Optional[Callable] = None,
    dry_run: bool = False
) -> Dict[str, Any]:
    """
    Send bulk emails asynchronously (convenience function).
    """
    config = SMTPServerConfig.from_dict(smtp_config)
    pool = SMTPConnectionPool(
        configs=[config],
        pool_size_per_server=min(concurrency // 5, 10)
    )
    
    rate_limiter = RateLimiter(RateLimiterConfig(
        per_minute=config.max_per_minute,
        per_hour=config.max_per_hour
    ))
    
    sender = AsyncEmailSender(
        connection_pool=pool,
        rate_limiter=rate_limiter,
        default_from_email=from_email,
        default_from_name=from_name or from_email,
        dry_run=dry_run
    )
    
    try:
        result = await sender.send_bulk(
            recipients=recipients,
            subject_template=subject_template,
            html_template=html_template,
            from_email=from_email,
            from_name=from_name,
            concurrency=concurrency,
            progress_callback=progress_callback
        )
        
        return result.to_dict()
        
    finally:
        await pool.close_all()


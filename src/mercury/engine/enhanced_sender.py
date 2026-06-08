"""Enhanced async email sender with advanced error handling."""

import asyncio
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, UTC
import uuid

from .async_sender import AsyncEmailSender, EmailResult, BulkSendResult
from .error_recovery import ErrorRecoveryManager, RecoveryStrategy
from .error_aggregator import ErrorAggregator
from ..services.dead_letter_service import DeadLetterService
from ..utils.logging_context import get_context_logger, EmailOperationContext

logger = get_context_logger(__name__)


class EnhancedAsyncEmailSender(AsyncEmailSender):
    """
    Enhanced email sender with advanced error handling.

    Features:
    - Error recovery strategies
    - Automatic SMTP server switching
    - Dead letter queue for permanent failures
    - Error aggregation for bulk operations
    - Structured logging with full context
    """

    def __init__(
        self,
        connection_pool,
        dead_letter_service: Optional[DeadLetterService] = None,
        error_recovery_manager: Optional[ErrorRecoveryManager] = None,
        **kwargs,
    ):
        """
        Initialize enhanced sender.

        Args:
            connection_pool: SMTP connection pool
            dead_letter_service: Service for dead letter queue
            error_recovery_manager: Error recovery manager
            **kwargs: Arguments for parent class
        """
        super().__init__(connection_pool, **kwargs)

        self.dead_letter_service = dead_letter_service
        self.error_recovery = error_recovery_manager or ErrorRecoveryManager()
        self._current_aggregator: Optional[ErrorAggregator] = None

    async def send_email_with_recovery(
        self,
        recipient: str,
        subject: str,
        html_body: str,
        from_email: Optional[str] = None,
        from_name: Optional[str] = None,
        correlation_id: Optional[str] = None,
        campaign_id: Optional[int] = None,
        max_recovery_attempts: int = 3,
        **kwargs,
    ) -> EmailResult:
        """
        Send email with automatic error recovery.

        Args:
            recipient: Email recipient
            subject: Email subject
            html_body: HTML content
            from_email: Sender email
            from_name: Sender name
            correlation_id: Tracking ID
            campaign_id: Campaign ID
            max_recovery_attempts: Maximum recovery attempts
            **kwargs: Additional arguments

        Returns:
            EmailResult with detailed error context
        """
        correlation_id = correlation_id or str(uuid.uuid4())
        from_email = from_email or self.default_from_email
        from_name = from_name or self.default_from_name

        attempt = 0
        current_smtp = kwargs.get("preferred_smtp")
        # A caller-supplied preferred_smtp is a hard pin: SWITCH_SERVER
        # recovery must not redirect the send to a different server, or the
        # pin's whole point (matching auth identity to From: header) is lost.
        smtp_pinned_by_caller = current_smtp is not None

        with EmailOperationContext(
            operation="send_email",
            recipient=recipient,
            campaign_id=campaign_id,
            correlation_id=correlation_id,
        ) as ctx_logger:
            while attempt < max_recovery_attempts:
                try:
                    # Attempt send
                    result = await super().send_email(
                        recipient=recipient,
                        subject=subject,
                        html_body=html_body,
                        from_email=from_email,
                        from_name=from_name,
                        correlation_id=correlation_id,
                        preferred_smtp=current_smtp,
                        **{k: v for k, v in kwargs.items() if k != "preferred_smtp"},
                    )

                    if result.success:
                        # Clear recovery tracking on success
                        self.error_recovery.clear_tracking(correlation_id)
                        return result

                    # Handle failure with recovery logic
                    error = Exception(result.error or "Unknown error")

                    # Create appropriate exception based on error type
                    if result.is_transient:
                        from ..exceptions import TransientSMTPError

                        error = TransientSMTPError(result.error, smtp_server=result.smtp_server)
                    else:
                        from ..exceptions import PermanentSMTPError

                        error = PermanentSMTPError(result.error, smtp_server=result.smtp_server)

                    # Decide recovery strategy
                    decision = self.error_recovery.decide_recovery(
                        error=error,
                        current_smtp=current_smtp or result.smtp_server,
                        correlation_id=correlation_id,
                        retry_count=attempt,
                    )

                    ctx_logger.info(
                        f"Recovery decision: {decision.strategy.value}",
                        should_retry=decision.should_retry,
                        reason=decision.reason,
                    )

                    # Handle based on strategy
                    if decision.strategy == RecoveryStrategy.DEAD_LETTER:
                        # Move to dead letter queue
                        if self.dead_letter_service:
                            self.dead_letter_service.add_dead_letter(
                                recipient=recipient,
                                subject=subject,
                                html_body=html_body,
                                from_email=from_email,
                                from_name=from_name,
                                campaign_id=campaign_id,
                                correlation_id=correlation_id,
                                error_type=result.error_type,
                                error_message=result.error or "",
                                smtp_server=result.smtp_server,
                            )
                        return result

                    elif decision.strategy == RecoveryStrategy.SWITCH_SERVER:
                        if smtp_pinned_by_caller:
                            ctx_logger.info(
                                "Ignoring SWITCH_SERVER: caller pinned preferred_smtp",
                                pinned_smtp=current_smtp,
                                rejected_alternative=decision.alternative_smtp,
                            )
                            if decision.retry_delay > 0:
                                await asyncio.sleep(decision.retry_delay)
                        else:
                            current_smtp = decision.alternative_smtp
                            kwargs["preferred_smtp"] = current_smtp
                            ctx_logger.info("Switching to alternative SMTP", new_smtp=current_smtp)

                    elif decision.strategy == RecoveryStrategy.DELAY_RETRY:
                        # Wait before retry
                        if decision.retry_delay > 0:
                            await asyncio.sleep(decision.retry_delay)

                    elif not decision.should_retry:
                        return result

                    attempt += 1

                except Exception as e:
                    ctx_logger.error("Unexpected error in recovery", error=e)
                    raise

            # All recovery attempts exhausted
            ctx_logger.error("All recovery attempts exhausted", attempts=max_recovery_attempts)

            return EmailResult(
                success=False,
                recipient=recipient,
                correlation_id=correlation_id,
                timestamp=datetime.now(UTC),
                error=f"All {max_recovery_attempts} recovery attempts failed",
                error_type="recovery_exhausted",
            )

    async def send_bulk_with_aggregation(
        self,
        recipients: List[Dict[str, Any]],
        subject_template: str,
        html_template: str,
        campaign_id: Optional[int] = None,
        enable_recovery: bool = True,
        **kwargs,
    ) -> Tuple[BulkSendResult, ErrorAggregator]:
        """
        Send bulk emails with error aggregation.

        Args:
            recipients: List of recipients
            subject_template: Subject template
            html_template: HTML template
            campaign_id: Campaign ID
            enable_recovery: Enable error recovery
            **kwargs: Additional arguments

        Returns:
            Tuple of (BulkSendResult, ErrorAggregator)
        """
        aggregator = ErrorAggregator()
        self._current_aggregator = aggregator

        # Override send method to collect errors
        async def send_with_aggregation(recipient_data: Dict[str, Any], index: int):
            recipient_email = recipient_data.get("email")
            correlation_id = str(uuid.uuid4())

            # Prepare email
            subject = subject_template
            body = html_template

            for key, value in recipient_data.items():
                placeholder = f"{{{{{key}}}}}"
                subject = subject.replace(placeholder, str(value))
                body = body.replace(placeholder, str(value))

            # Send with recovery if enabled
            if enable_recovery:
                result = await self.send_email_with_recovery(
                    recipient=recipient_email,
                    subject=subject,
                    html_body=body,
                    correlation_id=correlation_id,
                    campaign_id=campaign_id,
                    **kwargs,
                )
            else:
                result = await self.send_email(
                    recipient=recipient_email,
                    subject=subject,
                    html_body=body,
                    correlation_id=correlation_id,
                    **kwargs,
                )

            # Aggregate errors
            if not result.success:
                aggregator.add_error(
                    error=Exception(result.error or "Unknown"),
                    recipient=recipient_email,
                    smtp_server=result.smtp_server,
                    is_transient=result.is_transient,
                )

            return result

        # Use parent's bulk sending logic but with our custom send function
        semaphore = asyncio.Semaphore(max(1, kwargs.get("concurrency", 50)))
        results = []
        start_time = datetime.now(UTC)

        async def send_with_semaphore(recipient_data, index):
            async with semaphore:
                return await send_with_aggregation(recipient_data, index)

        tasks = [send_with_semaphore(r, i) for i, r in enumerate(recipients)]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        processed_results = []
        for r in results:
            if isinstance(r, EmailResult):
                processed_results.append(r)
            elif isinstance(r, Exception):
                # Unexpected exception
                processed_results.append(
                    EmailResult(
                        success=False,
                        recipient="unknown",
                        correlation_id=str(uuid.uuid4()),
                        timestamp=datetime.now(UTC),
                        error=str(r),
                        error_type="unexpected_exception",
                    )
                )

                aggregator.add_error(r, "unknown", is_transient=False)

        end_time = datetime.now(UTC)
        duration = (end_time - start_time).total_seconds()
        success_count = sum(1 for r in processed_results if r.success)

        bulk_result = BulkSendResult(
            total=len(recipients),
            success=success_count,
            failed=len(recipients) - success_count,
            duration_seconds=duration,
            emails_per_second=len(recipients) / duration if duration > 0 else 0,
            start_time=start_time,
            end_time=end_time,
            results=processed_results,
        )

        # Log error summary
        if bulk_result.failed > 0:
            aggregator.log_summary()

        return bulk_result, aggregator

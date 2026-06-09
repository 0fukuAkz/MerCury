"""Email service — composing and sending emails with all features.

This module owns the ``EmailService`` orchestration class. The per-step
helpers it delegates to live alongside in this package:
``branding``, ``extras``, ``attachments``, ``obfuscation``.
"""

import asyncio
import logging
from datetime import datetime, UTC
from typing import Any, Awaitable, Callable, Dict, List, Optional

from ...engine.async_sender import AsyncEmailSender, BulkSendResult, EmailResult
from ...engine.rate_limiter import RateLimiter, RateLimiterConfig
from ...engine.retry_queue import RetryQueue
from ...features.generators import AttachmentGenerator, GeneratorConfig
from ...features.placeholders import PlaceholderProcessor
from ...features.rotation import RotationManager, RotationStrategy
from ...features.template_engine import TemplateEngine
from ..bounce_service import BounceService
from ..dead_letter_service import DeadLetterService
from ..smtp_service import SMTPService
from ..tracking_service import TrackingService
from .attachments import materialize_library_attachments
from .branding import resolve_branding
from .config import EmailConfig
from .context import SendContext
from .extras import build_extras, generate_qr_data_url
from .obfuscation import apply_obfuscation

logger = logging.getLogger(__name__)


class EmailService:
    """Service for composing and sending emails."""

    def __init__(self, smtp_service: SMTPService):
        """
        Initialize email service.

        Args:
            smtp_service: SMTP service instance
        """
        self.smtp_service = smtp_service
        self._sender: Optional[AsyncEmailSender] = None
        self._rate_limiter: Optional[RateLimiter] = None
        self._retry_queue: Optional[RetryQueue] = None
        self._template_engine: Optional[TemplateEngine] = None
        self._rotation_manager: Optional[RotationManager] = None
        self._attachment_generator: Optional[AttachmentGenerator] = None
        self._tracking_service: Optional[TrackingService] = None
        self._dead_letter_service: Optional[DeadLetterService] = None
        self._placeholder_processor: Optional[PlaceholderProcessor] = None
        self.bounce_service = BounceService()

        # Default configuration
        self.config = EmailConfig()

        # Populated by send_single — let callers (e.g. the test-email
        # route) read structured diagnostics about the most recent send.
        self.last_send_diagnostics: Dict[str, Any] = {}

    def configure(self, config: EmailConfig):
        """Configure email service."""
        self.config = config

        # Setup rate limiter
        if config.rate_per_minute > 0 or config.rate_per_hour > 0:
            self._rate_limiter = RateLimiter(
                RateLimiterConfig(per_minute=config.rate_per_minute, per_hour=config.rate_per_hour)
            )

        # Setup template engine
        if config.template_path or config.html_content:
            self._template_engine = TemplateEngine(
                template_path=config.template_path,
                html_content=config.html_content,
                placeholders_path=config.placeholders_path,
            )
            self._template_engine.config.enable_qr_code = config.enable_qr_code
            self._placeholder_processor = self._template_engine.placeholder_processor
        else:
            # Standalone processor when no template engine is configured
            static_ph = {}
            if config.placeholders_path:
                try:
                    import json
                    import yaml as _yaml

                    with open(config.placeholders_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    if config.placeholders_path.endswith((".yaml", ".yml")):
                        static_ph = _yaml.safe_load(content) or {}
                    else:
                        static_ph = json.loads(content)
                except Exception:
                    pass
            self._placeholder_processor = PlaceholderProcessor(static_ph)

        # Setup rotation
        self._rotation_manager = RotationManager()
        strategy = (
            RotationStrategy(config.rotation_strategy)
            if config.rotation_strategy
            else RotationStrategy.ROUND_ROBIN
        )

        if config.subjects and len(config.subjects) > 1:
            self._rotation_manager.register("subjects", config.subjects, strategy)

        # Pair (from_name, from_email) into a single rotation set so they
        # always advance together — prevents Alice's name going out with
        # carol@example.com's address when the two lists have different
        # lengths or hit different rotation indices.
        #
        # Strategy:
        #   - Both lists present → register paired 'sender_identity' tuples.
        #     Lengths are aligned by zip (shorter list wins; leftover entries
        #     in the longer list are dropped, which is intentional — a name
        #     without a matching email, or vice-versa, is a config error).
        #   - Only names → register 'from_names' for display-name rotation;
        #     from_email stays static.
        #   - Only emails → register 'from_emails' for address rotation;
        #     from_name stays static.
        #   - Neither → both are static (no rotation).
        _has_names = bool(config.from_names)
        _has_emails = bool(config.from_emails)

        if _has_names and _has_emails:
            # Paired rotation: (name, email) tuples advance atomically.
            paired = list(zip(config.from_names, config.from_emails))
            self._rotation_manager.register("sender_identity", paired, strategy)
            # Warn about address-ownership mismatches in the paired set.
            self._warn_unowned_from_emails(config.from_emails)
            if len(config.from_names) != len(config.from_emails):
                logger.warning(
                    "from_names (%d entries) and from_emails (%d entries) differ "
                    "in length — paired rotation uses the shorter list (%d pairs). "
                    "Extra entries in the longer list are ignored.",
                    len(config.from_names),
                    len(config.from_emails),
                    len(paired),
                )
        elif _has_names:
            self._rotation_manager.register("from_names", config.from_names, strategy)
        elif _has_emails:
            self._rotation_manager.register("from_emails", config.from_emails, strategy)
            self._warn_unowned_from_emails(config.from_emails)

        if config.templates and len(config.templates) > 1:
            self._rotation_manager.register("templates", config.templates, strategy)

        if config.links and len(config.links) > 0:
            self._rotation_manager.register("links", config.links, strategy)

        # Merge operator-defined custom placeholders into the processor.
        # Active rows from the custom_placeholders table override any
        # built-in of the same name (operator intent > defaults) but
        # per-recipient CSV data still wins at process() time.
        self._merge_custom_placeholders()

        # Setup attachment generator
        self._attachment_generator = AttachmentGenerator(GeneratorConfig())

        # Setup tracking service: requires both opt-in AND a base URL.
        # TrackingService no longer accepts a localhost fallback, so a campaign
        # that enables tracking without configuring tracking_base_url is silently
        # downgraded to "tracking off" rather than crashed.
        if config.enable_tracking and config.tracking_base_url:
            self._tracking_service = TrackingService(base_url=config.tracking_base_url)

        # Setup dead letter service
        try:
            from ...data.database import get_session_direct
            from ...data.repositories.dead_letter import DeadLetterRepository

            session = get_session_direct()
            self._dead_letter_service = DeadLetterService(DeadLetterRepository(session))
        except Exception as e:
            logger.warning(f"Dead letter service not available: {e}")

    def get_sender(self) -> AsyncEmailSender:
        """Get or create async email sender."""
        if self._sender is None:
            connection_pool = self.smtp_service.get_connection_pool(
                pool_size_per_server=max(5, self.config.concurrency // 10),
                ip_warmup_mode=self.config.ip_warmup_mode,
            )
            self._sender = AsyncEmailSender(
                connection_pool=connection_pool,
                rate_limiter=self._rate_limiter,
                retry_queue=self._retry_queue,
                default_from_email=self.config.from_emails[0] if self.config.from_emails else "",
                default_from_name=self.config.from_names[0] if self.config.from_names else "",
                dry_run=self.config.dry_run,
            )

        return self._sender

    async def send_single(
        self,
        recipient: str,
        subject: Optional[str] = None,
        html_body: Optional[str] = None,
        from_email: Optional[str] = None,
        from_name: Optional[str] = None,
        reply_to: Optional[str] = None,
        placeholders: Optional[Dict[str, Any]] = None,
        link: Optional[str] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> EmailResult:
        """
        Send single email with all features.

        Args:
            recipient: Recipient email address
            subject: Email subject (uses rotation if not provided)
            html_body: HTML content (uses template if not provided)
            from_email: Sender email
            from_name: Sender name (uses rotation if not provided)
            reply_to: Reply-to address
            placeholders: Custom placeholder values
            link: Link for QR code and {{link}} placeholder
            attachments: Pre-prepared attachments

        Returns:
            EmailResult with send status
        """
        placeholders = placeholders or {}
        placeholders["email"] = recipient

        # Validate the recipient at the boundary. An address without '@' is
        # invalid by definition, and several downstream helpers (branding,
        # domain-derived placeholders, logo auto-fetch) parse it by splitting
        # on '@' — a malformed value used to surface as an opaque
        # "list index out of range" IndexError deep in a parser, which the
        # bulk gather() path then logged with recipient='unknown'. Failing
        # fast here turns a cryptic crash into a clear, per-recipient result.
        if not recipient or "@" not in recipient:
            return EmailResult(
                success=False,
                recipient=recipient or "unknown",
                correlation_id=None,
                timestamp=datetime.now(UTC),
                error=f"Invalid recipient address: {recipient!r}",
                error_type="invalid_recipient",
                is_transient=False,
            )

        # Resolve rotating header values (caller wins if explicit).
        subject = self._resolve_rotated("subjects", subject, self.config.subject)

        # Resolve sender identity. When both name and email are configured
        # for rotation they are stored as paired (name, email) tuples in
        # 'sender_identity' so they always advance atomically. When only
        # one of the two is being rotated the individual sets are used.
        if (
            from_name is None
            and from_email is None
            and self._rotation_manager
            and self._rotation_manager.is_registered("sender_identity")
        ):
            _identity = self._rotation_manager.get_next(
                "sender_identity", (self.config.from_names[0] if self.config.from_names else "", self.config.from_emails[0] if self.config.from_emails else "")
            )
            from_name, from_email = _identity
        else:
            from_name = self._resolve_rotated("from_names", from_name, self.config.from_names[0] if self.config.from_names else "")
            from_email = self._resolve_rotated("from_emails", from_email, self.config.from_emails[0] if self.config.from_emails else "")

        ctx = SendContext(
            recipient=recipient,
            placeholders=placeholders,
            link=link,
            config=self.config,
        )

        # Build the substitution-extras dicts up front (qr + branding + link/url).
        qr_data_url = generate_qr_data_url(ctx)
        branding = resolve_branding(ctx)
        body_extras, header_extras = build_extras(ctx, qr_data_url, branding)

        # Pre-render: check whether {{qr_code}} is referenced *before* the
        # template engine substitutes it away, so we can surface a
        # diagnostic when the operator clearly intended a QR but no
        # link/enable combination was supplied. Looked up against the
        # raw source — either the explicit html_body the route passed,
        # or the engine's current template content. Both render paths
        # silently substitute empty when qr_data_url is None, which is
        # the behavior the operator perceives as "QR not working."
        qr_referenced = False
        if html_body and "{{qr_code" in html_body:
            qr_referenced = True
        elif (
            html_body is None
            and self._template_engine
            and "{{qr_code" in (getattr(self._template_engine, "_template_content", "") or "")
        ):
            qr_referenced = True

        if qr_referenced and not qr_data_url:
            logger.warning(
                "Template contains {{qr_code}} but "
                f"enable_qr_code={self.config.enable_qr_code}, link={link!r}; "
                "rendering as empty string. Set both 'Enable QR code' AND "
                "a primary link (or per-send link) for the placeholder to "
                "resolve to an <img> tag."
            )

        # Track per-send diagnostics surfaced via last_send_diagnostics so
        # the API (e.g. test-email route) can include them in the response.
        self.last_send_diagnostics: Dict[str, Any] = {
            "qr_code_referenced_in_body": qr_referenced,
            "qr_code_resolved": qr_data_url is not None,
            "enable_qr_code": bool(self.config.enable_qr_code),
            "link_present": bool(link),
        }

        # Render body
        if html_body is None and self._template_engine:
            # Check for template rotation
            if self._rotation_manager and self._rotation_manager.is_registered("templates"):
                template_path = self._rotation_manager.get_next("templates")
                self._template_engine.load_template(template_path)

            html_body = self._template_engine.render(
                recipient=recipient,
                recipient_data=placeholders,
                extra_placeholders=body_extras,
                qr_code_data_url=qr_data_url,
                link=link,
            )
        elif html_body and self._placeholder_processor:
            html_body = self._placeholder_processor.process(html_body, placeholders, body_extras)

        if not html_body:
            # Default fallback so the inbox shows *something* rather than
            # an empty multipart alternative (some clients render that as
            # blank). Operators can opt out for pixel-only / ping sends
            # by setting include_default_body=False on the config.
            html_body = f"<p>Email to {recipient}</p>" if self.config.include_default_body else ""

        # Inject tracking if enabled
        tracking_email_id = None
        if self._tracking_service and self.config.enable_tracking:
            tracking_email_id = self._tracking_service.generate_email_id(recipient)
            html_body = self._tracking_service.inject_tracking(
                html_body,
                email_id=tracking_email_id,
                recipient=recipient,
                track_opens=self.config.track_opens,
                track_clicks=self.config.track_clicks,
            )

        # Apply placeholders to headers. Subject, From, Reply-To all use
        # header_extras (link/url present; qr_code blanked so accidental
        # references render empty, not as raw markup). reply_to goes
        # through the same path as the other headers — earlier code
        # skipped it entirely and {{var}} silently leaked into the inbox.
        if self._placeholder_processor:
            if subject:
                subject = self._placeholder_processor.process(subject, placeholders, header_extras)
            if from_name and "{{" in from_name:
                from_name = self._placeholder_processor.process(
                    from_name, placeholders, header_extras
                )
            if from_email and "{{" in from_email:
                from_email = self._placeholder_processor.process(
                    from_email, placeholders, header_extras
                )
            if reply_to and "{{" in reply_to:
                reply_to = self._placeholder_processor.process(
                    reply_to, placeholders, header_extras
                )

        # Library attachment materialization
        library_files = materialize_library_attachments(
            ctx,
            body_extras,
            header_extras,
            self._placeholder_processor,
            self._attachment_generator,
        )
        if library_files:
            attachments = (attachments or []) + library_files

        # Convert whole body to image (after placeholders + tracking)
        if self.config.send_as_image and self._attachment_generator:
            image_url = self._attachment_generator.image.generate_data_url(html_body)
            html_body = f'<img src="{image_url}" alt="Email" style="max-width:100%;" />'

        # Apply encoding/obfuscation from global settings
        html_body, force_base64 = apply_obfuscation(html_body, attachments)

        # Send email
        sender = self.get_sender()

        logger.info(
            "[attach] handing off to sender: "
            + str(
                [
                    {
                        "filename": a.get("filename"),
                        "content_type": a.get("content_type"),
                        "data_type": type(a.get("data")).__name__,
                        "data_len": len(a.get("data") or b""),
                    }
                    for a in (attachments or [])
                ]
            )
        )

        # Phrase-only From: header — when hide_from_email_header is on,
        # pass an empty from_email so the engine's `formataddr((name, ''))`
        # produces just the display name. The SMTP envelope (MAIL FROM)
        # still uses the connection's authenticated user, set by the
        # underlying aiosmtplib send path.
        resolved_from_email = (
            "" if self.config.hide_from_email_header else (from_email or (self.config.from_emails[0] if self.config.from_emails else ""))
        )

        # Mail priority headers (RFC 2156 / MS extensions).
        # Only inject when priority differs from normal (3) to keep
        # headers clean for the common case.
        priority_headers: Dict[str, str] = {}
        _mp = self.config.mail_priority
        if _mp == "1":
            priority_headers = {
                "X-Priority": "1",
                "X-MSMail-Priority": "High",
                "Importance": "High",
            }
        elif _mp == "2":
            priority_headers = {
                "X-Priority": "2",
                "X-MSMail-Priority": "High",
                "Importance": "High",
            }
        elif _mp == "4":
            priority_headers = {
                "X-Priority": "4",
                "X-MSMail-Priority": "Low",
                "Importance": "Low",
            }
        elif _mp == "5":
            priority_headers = {
                "X-Priority": "5",
                "X-MSMail-Priority": "Low",
                "Importance": "Low",
            }

        result = await sender.send_email(
            recipient=recipient,
            subject=subject,
            html_body=html_body,
            from_email=resolved_from_email,
            from_name=from_name,
            reply_to=reply_to or self.config.reply_to,
            attachments=attachments,
            headers=priority_headers or None,
            correlation_id=tracking_email_id,
            force_base64_body=force_base64,
        )

        # On failure: add to dead letter queue. Skip for server-side errors
        # (auth / connection) — these are infrastructure problems, not
        # recipient-level rejections.
        _SERVER_ERROR_TYPES = {"authentication_error", "connection_error"}
        if not result.success and result.error:
            # Categorize bounces for better error tracking
            bounce_type, category = self.bounce_service.categorize_bounce(None, result.error)
            if category.value != "unknown":
                result.error_type = category.value
            
            if bounce_type.value in {"hard", "soft"}:
                setattr(result, "is_bounce", True)
                self.bounce_service.process_bounce(
                    email=recipient,
                    error_message=result.error,
                    smtp_code=None,
                    campaign_id=str(getattr(self.config, "campaign_id", "")) if getattr(self.config, "campaign_id", None) else None
                )

            if self._dead_letter_service and result.error_type not in _SERVER_ERROR_TYPES:
                try:
                    self._dead_letter_service.add_dead_letter(
                        recipient=recipient,
                        subject=subject or "",
                        html_body=html_body or "",
                        from_email=from_email or (self.config.from_emails[0] if self.config.from_emails else ""),
                        error_type=result.error_type or "send_failure",
                        error_message=result.error or "Unknown error",
                        from_name=from_name,
                        smtp_server=result.smtp_server,
                        campaign_id=getattr(self.config, "campaign_id", None),
                    )
                except Exception as e:
                    logger.warning(f"Failed to add dead letter: {e}")

        return result

    def _merge_custom_placeholders(self) -> None:
        """Load active CustomPlaceholder rows into the processor.

        Custom placeholders ride on the standalone PlaceholderProcessor's
        ``static_placeholders`` dict, the same surface that
        ``placeholders_path`` (file-based) populates. Custom rows are
        merged *after* the file so they take precedence on collision —
        operator-defined data wins over file-defined defaults. Per-
        recipient CSV columns still win over both at process() time.

        Best-effort: a DB error here must not break a send.
        """
        if self._placeholder_processor is None:
            return
        try:
            from ...data.database import session_scope
            from ...data.repositories import CustomPlaceholderRepository

            with session_scope() as session:
                rows = CustomPlaceholderRepository(session).list_active()
                for row in rows:
                    self._placeholder_processor.static_placeholders[row.name] = row.value or ""
        except Exception as e:
            logger.warning(
                "Could not load custom placeholders (sends will skip them): %s",
                e,
            )

    def _warn_unowned_from_emails(self, from_emails: List[str]) -> None:
        """Surface from_emails rotation entries that no SMTP server owns.

        An unowned From routes through plain rotation as a best-effort
        fallback, which is exactly the path that gateway-side relays
        reject with 5.7.0 "From is not one of your addresses". Warning
        here turns a confusing intermittent send failure into something
        an operator can fix before launching the campaign.
        """
        try:
            pool = self.smtp_service.get_connection_pool(
                ip_warmup_mode=getattr(self.config, "ip_warmup_mode", False)
            )
        except Exception:
            return  # pool not yet built; nothing to validate against

        unowned = [addr for addr in from_emails if pool.select_server_for_from(addr) is None]
        if unowned:
            logger.warning(
                "[route] from_emails rotation contains %d address(es) with "
                "no owning SMTP server: %s. Sends from these will fall back "
                "to plain rotation and may be rejected with 5.7.0 by the "
                "upstream gateway. Configure server.from_email to match, "
                "or remove the addresses from the rotation.",
                len(unowned),
                unowned,
            )

    def _resolve_rotated(self, key: str, explicit: Optional[str], fallback: str) -> str:
        """Pick a rotated value when caller didn't supply one.

        Caller-provided value always wins; otherwise the rotation manager
        rotates if registered for ``key``; otherwise we fall back to the
        configured static value.
        """
        if explicit is not None:
            return explicit
        if self._rotation_manager and self._rotation_manager.is_registered(key):
            return self._rotation_manager.get_next(key, fallback)
        return fallback

    def _enrich_recipients_with_last_event(self, recipients: List[Dict[str, Any]]) -> None:
        """Mutate ``recipients`` in place to fill missing ip/user_agent.

        For each recipient WITHOUT ``ip``/``ip_address`` or
        ``user_agent``/``ua`` already set, look up the most-recent open or
        click for that email address and inject the IP+UA so the placeholder
        engine can resolve {{location.*}} and {{ua.*}}.

        Recipients that already carry those columns (CSV-supplied) are left
        alone — caller-provided data wins over historical inference.
        """
        from ...data.database import session_scope
        from ...data.repositories.logs import LogRepository

        # Collect recipients that actually need enrichment — avoid the DB
        # roundtrip if every row already has ip/ua from CSV.
        needs: List[str] = []
        for r in recipients:
            email = (r or {}).get("email")
            if not email:
                continue
            has_ip = bool(r.get("ip") or r.get("ip_address"))
            has_ua = bool(r.get("user_agent") or r.get("ua"))
            if not (has_ip and has_ua):
                needs.append(email)

        if not needs:
            return

        with session_scope() as session:
            repo = LogRepository(session)
            last_events = repo.get_last_events_bulk(needs)

        if not last_events:
            return

        for r in recipients:
            email = r.get("email")
            ev = last_events.get(email) if email else None
            if not ev:
                continue
            ip, ua = ev
            if ip and not (r.get("ip") or r.get("ip_address")):
                r["ip"] = ip
            if ua and not (r.get("user_agent") or r.get("ua")):
                r["user_agent"] = ua

    async def send_bulk(
        self,
        recipients: List[Dict[str, Any]],
        subject: Optional[str] = None,
        html_template: Optional[str] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
        shutdown_event: Optional[asyncio.Event] = None,
    ) -> BulkSendResult:
        """
        Send bulk emails to multiple recipients.

        Args:
            recipients: List of recipient dicts with 'email' and placeholders
            subject: Subject template (uses rotation subjects if not provided)
            html_template: HTML template (uses configured template if not provided)
            progress_callback: Async callback for progress updates
            shutdown_event: Optional event to signal early abort

        Returns:
            BulkSendResult with statistics
        """
        start_time = datetime.now(UTC)
        total = len(recipients)

        # Backfill ip/user_agent from prior tracking events. Cheap when the
        # recipient already has those columns (we don't overwrite); useful
        # when they don't, so {{location.*}} / {{ua.*}} can resolve. One
        # bulk query rather than N — see LogRepository.get_last_events_bulk.
        try:
            self._enrich_recipients_with_last_event(recipients)
        except Exception as e:
            # Enrichment is best-effort; never block a send on it.
            logger.warning(f"Recipient geo/UA enrichment failed: {e}")

        # Use semaphore for concurrency
        semaphore = asyncio.Semaphore(max(1, self.config.concurrency))

        async def send_wrapper(index: int, recipient_data: Dict[str, Any]) -> EmailResult:
            try:
                if shutdown_event and shutdown_event.is_set():
                    result = EmailResult(
                        success=False,
                        recipient=recipient_data["email"],
                        correlation_id=None,
                        timestamp=datetime.now(UTC),
                        error="Campaign cancelled",
                        error_type="cancelled",
                        is_transient=False,
                    )
                else:
                    async with semaphore:
                        if shutdown_event and shutdown_event.is_set():
                            result = EmailResult(
                                success=False,
                                recipient=recipient_data["email"],
                                correlation_id=None,
                                timestamp=datetime.now(UTC),
                                error="Campaign cancelled",
                                error_type="cancelled",
                                is_transient=False,
                            )
                        else:
                            # Get link rotation if available
                            link_to_use = None
                            if self._rotation_manager and self._rotation_manager.is_registered(
                                "links"
                            ):
                                link_to_use = self._rotation_manager.get_next("links")

                            # Use send_single to ensure full feature support (rotation, tracking, etc.)
                            result = await self.send_single(
                                recipient=recipient_data["email"],
                                subject=subject,  # Passes None implies use config/rotation
                                html_body=None,  # Force template rendering
                                placeholders=recipient_data,
                                link=link_to_use,
                            )
            except Exception as e:
                import traceback

                logger.error(
                    f"send_wrapper exception traceback: {''.join(traceback.format_exception(type(e), e, e.__traceback__))}"
                )
                result = EmailResult(
                    success=False,
                    recipient=recipient_data.get("email", "unknown"),
                    correlation_id=None,
                    timestamp=datetime.now(UTC),
                    error=str(e),
                    error_type="exception",
                    is_transient=False,
                )

            if progress_callback:
                await progress_callback(
                    {
                        "index": index,
                        "total": total,
                        "recipient": recipient_data.get("email", "unknown"),
                        "success": result.success,
                        "error_type": result.error_type if not result.success else None,
                        "error_message": result.error if not result.success else None,
                        "is_bounce": getattr(result, "is_bounce", False),
                        "percent": round((index + 1) / total * 100, 1) if total > 0 else 100.0,
                        "result": result,  # pass the full object for db logging
                    }
                )

            return result

        # Create tasks
        tasks = [send_wrapper(i, r) for i, r in enumerate(recipients)]

        # Execute
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        processed_results = []
        success_count = 0

        for recipient_data, r in zip(recipients, results):
            if isinstance(r, Exception):
                import traceback

                logger.error(
                    f"send_wrapper exception traceback: {''.join(traceback.format_exception(type(r), r, r.__traceback__))}"
                )
                # Pair the exception with its originating recipient by index
                # (gather preserves order) so an unexpected error that escapes
                # send_single still records who failed instead of 'unknown'.
                processed_results.append(
                    EmailResult(
                        success=False,
                        recipient=(recipient_data or {}).get("email", "unknown"),
                        correlation_id=None,
                        timestamp=datetime.now(UTC),
                        error=str(r),
                        error_type="exception",
                    )
                )
            else:
                processed_results.append(r)
                if r.success:
                    success_count += 1

        end_time = datetime.now(UTC)
        duration = (end_time - start_time).total_seconds()

        return BulkSendResult(
            total=total,
            success=success_count,
            failed=total - success_count,
            duration_seconds=duration,
            emails_per_second=total / duration if duration > 0 else 0,
            start_time=start_time,
            end_time=end_time,
            results=processed_results,
        )

    def get_statistics(self) -> Dict[str, Any]:
        """Get sending statistics."""
        stats = {
            "config": {
                "from_email": self.config.from_emails[0] if self.config.from_emails else "",
                "from_name": self.config.from_names[0] if self.config.from_names else "",
                "dry_run": self.config.dry_run,
                "concurrency": self.config.concurrency,
            }
        }

        if self._sender:
            stats["sender"] = self._sender.get_stats()

        if self._rotation_manager:
            stats["rotation"] = self._rotation_manager.get_statistics()

        return stats

    async def close(self):
        """Clean up resources."""
        if self._retry_queue:
            await self._retry_queue.stop()

        await self.smtp_service.close()
        self._sender = None

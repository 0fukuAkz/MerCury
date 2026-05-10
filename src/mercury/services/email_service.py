"""Email service for sending emails with all features."""

import asyncio
import logging
import os
from typing import Dict, Any, Optional, List, Callable, Awaitable
from datetime import datetime, UTC
from dataclasses import dataclass

from ..engine.async_sender import AsyncEmailSender, EmailResult, BulkSendResult
from ..engine.rate_limiter import RateLimiter, RateLimiterConfig
from ..engine.retry_queue import RetryQueue
from ..features.template_engine import TemplateEngine
from ..features.placeholders import PlaceholderProcessor
from ..features.generators import AttachmentGenerator, GeneratorConfig
from ..features.rotation import RotationManager, RotationStrategy
from .smtp_service import SMTPService
from .tracking_service import TrackingService
from .dead_letter_service import DeadLetterService

logger = logging.getLogger(__name__)


@dataclass
class EmailConfig:
    """Email configuration."""
    subject: str = ""
    from_email: str = ""
    from_name: str = ""
    from_emails: Optional[List[str]] = None
    reply_to: str = ""
    template_path: Optional[str] = None
    placeholders_path: Optional[str] = None
    html_content: Optional[str] = None
    
    # Attachments
    attachment_path: Optional[str] = None
    attachment_type: Optional[str] = None  # pdf, docx, qr, image
    
    # Features
    enable_qr_code: bool = False
    send_as_image: bool = False
    convert_attachment: bool = False
    
    # Tracking
    enable_tracking: bool = True
    track_opens: bool = True
    track_clicks: bool = True
    tracking_base_url: Optional[str] = None
    
    # Sending options
    dry_run: bool = False
    concurrency: int = 50
    rate_per_minute: int = 0
    rate_per_hour: int = 0
    
    # Rotation
    subjects: Optional[List[str]] = None
    from_names: Optional[List[str]] = None
    templates: Optional[List[str]] = None
    links: Optional[List[str]] = None
    rotation_strategy: str = "round_robin"

    @classmethod
    def from_campaign_config(cls, config: "Any") -> "EmailConfig":
        """Build an EmailConfig from a CampaignConfig instance."""
        return cls(
            subject=config.subject,
            from_email=config.from_email,
            from_name=config.from_name,
            reply_to=config.reply_to,
            template_path=config.template_path,
            html_content=config.html_content,
            placeholders_path=config.placeholders_path,
            dry_run=config.dry_run,
            concurrency=config.concurrency,
            rate_per_minute=config.rate_per_minute,
            rate_per_hour=config.rate_per_hour,
            enable_qr_code=config.enable_qr_code,
            send_as_image=config.send_as_image,
            convert_attachment=config.convert_attachment,
            attachment_type=config.attachment_type,
            attachment_path=config.attachment_path,
            subjects=config.subjects,
            from_names=config.from_names,
            from_emails=config.from_emails,
            templates=config.templates,
            rotation_strategy=config.smtp_rotation,
            links=config.links,
            enable_tracking=config.enable_tracking,
            track_opens=config.track_opens,
            track_clicks=config.track_clicks,
            tracking_base_url=config.tracking_base_url or None,
        )


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
        
        # Default configuration
        self.config = EmailConfig()
    
    def configure(self, config: EmailConfig):
        """Configure email service."""
        self.config = config
        
        # Setup rate limiter
        if config.rate_per_minute > 0 or config.rate_per_hour > 0:
            self._rate_limiter = RateLimiter(RateLimiterConfig(
                per_minute=config.rate_per_minute,
                per_hour=config.rate_per_hour
            ))
        
        # Setup template engine
        if config.template_path or config.html_content:
            self._template_engine = TemplateEngine(
                template_path=config.template_path,
                html_content=config.html_content,
                placeholders_path=config.placeholders_path
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
                    with open(config.placeholders_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    if config.placeholders_path.endswith(('.yaml', '.yml')):
                        static_ph = _yaml.safe_load(content) or {}
                    else:
                        static_ph = json.loads(content)
                except Exception:
                    pass
            self._placeholder_processor = PlaceholderProcessor(static_ph)
        
        # Setup rotation
        self._rotation_manager = RotationManager()
        strategy = RotationStrategy(config.rotation_strategy) if config.rotation_strategy else RotationStrategy.ROUND_ROBIN
        
        if config.subjects and len(config.subjects) > 1:
            self._rotation_manager.register('subjects', config.subjects, strategy)
        
        if config.from_names and len(config.from_names) >= 1:
            self._rotation_manager.register('from_names', config.from_names, strategy)
        
        if config.from_emails and len(config.from_emails) >= 1:
            self._rotation_manager.register('from_emails', config.from_emails, strategy)
        
        if config.templates and len(config.templates) > 1:
            self._rotation_manager.register('templates', config.templates, strategy)
        
        if config.links and len(config.links) > 0:
            self._rotation_manager.register('links', config.links, strategy)
        
        # Setup attachment generator
        self._attachment_generator = AttachmentGenerator(GeneratorConfig())
        
        # Setup tracking service
        if config.enable_tracking:
            self._tracking_service = TrackingService(
                base_url=config.tracking_base_url
            )
        
        # Setup dead letter service
        try:
            from ..data.database import get_session_direct
            from ..data.repositories.dead_letter import DeadLetterRepository
            session = get_session_direct()
            self._dead_letter_service = DeadLetterService(DeadLetterRepository(session))
        except Exception as e:
            logger.warning(f"Dead letter service not available: {e}")
    
    def get_sender(self) -> AsyncEmailSender:
        """Get or create async email sender."""
        if self._sender is None:
            connection_pool = self.smtp_service.get_connection_pool(
                pool_size_per_server=max(5, self.config.concurrency // 10)
            )
            
            self._sender = AsyncEmailSender(
                connection_pool=connection_pool,
                rate_limiter=self._rate_limiter,
                retry_queue=self._retry_queue,
                default_from_email=self.config.from_email,
                default_from_name=self.config.from_name,
                dry_run=self.config.dry_run
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
        attachments: Optional[List[Dict[str, Any]]] = None
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
        placeholders['email'] = recipient
        
        # Get rotating values
        if subject is None:
            if self._rotation_manager and self._rotation_manager.is_registered('subjects'):
                subject = self._rotation_manager.get_next('subjects', self.config.subject)
            else:
                subject = self.config.subject
        
        if from_name is None:
            if self._rotation_manager and self._rotation_manager.is_registered('from_names'):
                from_name = self._rotation_manager.get_next('from_names', self.config.from_name)
            else:
                from_name = self.config.from_name
        
        if from_email is None:
            if self._rotation_manager and self._rotation_manager.is_registered('from_emails'):
                from_email = self._rotation_manager.get_next('from_emails', self.config.from_email)
            else:
                from_email = self.config.from_email
        
        # Render template
        if html_body is None and self._template_engine:
            # Check for template rotation
            if self._rotation_manager and self._rotation_manager.is_registered('templates'):
                template_path = self._rotation_manager.get_next('templates')
                self._template_engine.load_template(template_path)
            
            html_body = self._template_engine.render(
                recipient=recipient,
                recipient_data=placeholders,
                link=link
            )
        elif html_body and self._placeholder_processor:
            # Body was passed directly (e.g. test email, API) — still apply placeholders
            extras = {'link': link or '', 'url': link or ''}

            # Generate QR code for {{qr_code}} tag when enabled
            if self.config.enable_qr_code and link:
                from ..features.generators import QRCodeGenerator
                qr_gen = QRCodeGenerator(GeneratorConfig())
                qr_data_url = qr_gen.generate_data_url(link)
                extras['qr_code'] = f'<img src="{qr_data_url}" alt="QR Code" />'
                extras['qr_code_url'] = qr_data_url

            html_body = self._placeholder_processor.process(html_body, placeholders, extras)
        
        if not html_body:
            html_body = f"<p>Email to {recipient}</p>"
        
        # Inject tracking if enabled
        tracking_email_id = None
        if self._tracking_service and self.config.enable_tracking:
            tracking_email_id = self._tracking_service.generate_email_id(recipient)
            html_body = self._tracking_service.inject_tracking(
                html_body,
                email_id=tracking_email_id,
                recipient=recipient,
                track_opens=self.config.track_opens,
                track_clicks=self.config.track_clicks
            )
        
        # Apply placeholders to subject
        if subject and self._placeholder_processor:
            subject = self._placeholder_processor.process(subject, placeholders)
        
        # Apply placeholders to from_name / from_email
        if from_name and self._placeholder_processor and '{{' in from_name:
            from_name = self._placeholder_processor.process(from_name, placeholders)
        if from_email and self._placeholder_processor and '{{' in from_email:
            from_email = self._placeholder_processor.process(from_email, placeholders)
        
        # Generate attachments if configured
        if attachments is None:
            # CHECK 1: Attachment Path is provided
            if self.config.attachment_path:
                current_attachment_path = self.config.attachment_path
                # Apply placeholders to path
                if placeholders:
                    for key, value in placeholders.items():
                        current_attachment_path = current_attachment_path.replace(f"{{{{{key}}}}}", str(value))

                # Option A: attachment_type set -> use generator with substituted path as template
                if self.config.attachment_type and self._attachment_generator:
                    attachment_data, filename, content_type = self._attachment_generator.generate_attachment(
                        attachment_type=self.config.attachment_type,
                        content=html_body,
                        placeholders=placeholders,
                        template_path=current_attachment_path,
                        link=link
                    )
                    attachments = [{
                        'data': attachment_data,
                        'filename': filename,
                        'content_type': content_type
                    }]

                # Option B: No attachment_type -> send the file on disk directly
                elif os.path.exists(current_attachment_path):
                    try:
                        import mimetypes
                        ctype, encoding = mimetypes.guess_type(current_attachment_path)
                        if ctype is None or encoding is not None:
                            ctype = 'application/octet-stream'

                        with open(current_attachment_path, 'rb') as f:
                            file_data = f.read()

                        attachments = [{
                            'data': file_data,
                            'filename': os.path.basename(current_attachment_path),
                            'content_type': ctype
                        }]
                    except Exception as e:
                        logger.error(f"Failed to read attachment {current_attachment_path}: {e}")

            # CHECK 2: No path, but Attachment Type set -> Convert Body to Attachment
            elif self.config.attachment_type and self._attachment_generator:
                attachment_data, filename, content_type = self._attachment_generator.generate_attachment(
                    attachment_type=self.config.attachment_type,
                    content=html_body,
                    placeholders=placeholders,
                    template_path=None,
                    link=link
                )
                attachments = [{
                    'data': attachment_data,
                    'filename': filename,
                    'content_type': content_type
                }]
        
        # Convert to image if configured
        if self.config.send_as_image and self._attachment_generator:
            image_url = self._attachment_generator.image.generate_data_url(html_body)
            html_body = f'<img src="{image_url}" alt="Email" style="max-width:100%;" />'

        # Apply encoding/obfuscation from global settings
        from .settings_service import SettingsService
        from ..features.encoding import (
            html_entity_encode, unicode_homoglyph_replace,
            url_encode_links, base64_encode_attachment
        )
        _enc_settings = SettingsService.get_settings()

        if _enc_settings.obfuscate_links:
            html_body = url_encode_links(html_body)
        if _enc_settings.encode_html_entities:
            html_body = html_entity_encode(html_body)
        if _enc_settings.encode_unicode_homoglyphs:
            html_body = unicode_homoglyph_replace(html_body)
        if _enc_settings.encode_attachments and attachments:
            for att in attachments:
                att['data'] = base64_encode_attachment(att['data'])

        _force_base64 = bool(_enc_settings.encode_body_base64)

        # Send email
        sender = self.get_sender()

        result = await sender.send_email(
            recipient=recipient,
            subject=subject,
            html_body=html_body,
            from_email=from_email or self.config.from_email,
            from_name=from_name,
            reply_to=reply_to or self.config.reply_to,
            attachments=attachments,
            correlation_id=tracking_email_id,
            force_base64_body=_force_base64
        )
        
        # On failure: add to dead letter queue.
        # Skip for server-side errors (auth / connection) — these are
        # infrastructure problems, not recipient-level rejections.
        _SERVER_ERROR_TYPES = {'authentication_error', 'connection_error'}
        if not result.success and result.error:
            if self._dead_letter_service and result.error_type not in _SERVER_ERROR_TYPES:
                try:
                    self._dead_letter_service.add_dead_letter(
                        recipient=recipient,
                        subject=subject or '',
                        html_body=html_body or '',
                        from_email=from_email or self.config.from_email,
                        error_type=result.error_type or 'send_failure',
                        error_message=result.error or 'Unknown error',
                        from_name=from_name,
                        smtp_server=result.smtp_server
                    )
                except Exception as e:
                    logger.warning(f"Failed to add dead letter: {e}")
        
        return result
    
    def _enrich_recipients_with_last_event(
        self, recipients: List[Dict[str, Any]]
    ) -> None:
        """Mutate ``recipients`` in place to fill missing ip/user_agent.

        For each recipient WITHOUT ``ip``/``ip_address`` or
        ``user_agent``/``ua`` already set, look up the most-recent open or
        click for that email address and inject the IP+UA so the placeholder
        engine can resolve {{location.*}} and {{ua.*}}.

        Recipients that already carry those columns (CSV-supplied) are left
        alone — caller-provided data wins over historical inference.
        """
        from ..data.database import session_scope
        from ..data.repositories.logs import LogRepository

        # Collect recipients that actually need enrichment — avoid the DB
        # roundtrip if every row already has ip/ua from CSV.
        needs: List[str] = []
        for r in recipients:
            email = (r or {}).get('email')
            if not email:
                continue
            has_ip = bool(r.get('ip') or r.get('ip_address'))
            has_ua = bool(r.get('user_agent') or r.get('ua'))
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
            email = r.get('email')
            ev = last_events.get(email) if email else None
            if not ev:
                continue
            ip, ua = ev
            if ip and not (r.get('ip') or r.get('ip_address')):
                r['ip'] = ip
            if ua and not (r.get('user_agent') or r.get('ua')):
                r['user_agent'] = ua

    async def send_bulk(
        self,
        recipients: List[Dict[str, Any]],
        subject: Optional[str] = None,
        html_template: Optional[str] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None
    ) -> BulkSendResult:
        """
        Send bulk emails to multiple recipients.
        
        Args:
            recipients: List of recipient dicts with 'email' and placeholders
            subject: Subject template (uses rotation subjects if not provided)
            html_template: HTML template (uses configured template if not provided)
            progress_callback: Async callback for progress updates
            
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
        semaphore = asyncio.Semaphore(self.config.concurrency)
        
        async def send_wrapper(index: int, recipient_data: Dict[str, Any]) -> EmailResult:
            async with semaphore:
                # Get link rotation if available
                link_to_use = None
                if self._rotation_manager and self._rotation_manager.is_registered('links'):
                    link_to_use = self._rotation_manager.get_next('links')

                # Use send_single to ensure full feature support (rotation, tracking, etc.)
                result = await self.send_single(
                    recipient=recipient_data['email'],
                    subject=subject, # Passes None implies use config/rotation
                    html_body=None,  # Force template rendering
                    placeholders=recipient_data,
                    link=link_to_use
                )
                
                if progress_callback:
                    await progress_callback({
                        'index': index,
                        'total': total,
                        'recipient': recipient_data['email'],
                        'success': result.success,
                        'percent': round((index + 1) / total * 100, 1)
                    })
                
                return result

        # Create tasks
        tasks = [send_wrapper(i, r) for i, r in enumerate(recipients)]
        
        # Execute
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        processed_results = []
        success_count = 0
        
        for r in results:
            if isinstance(r, Exception):
                processed_results.append(EmailResult(
                    success=False,
                    recipient="unknown", 
                    correlation_id=None,
                    timestamp=datetime.now(UTC),
                    error=str(r),
                    error_type="exception"
                ))
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
            results=processed_results
        )
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get sending statistics."""
        stats = {
            'config': {
                'from_email': self.config.from_email,
                'from_name': self.config.from_name,
                'dry_run': self.config.dry_run,
                'concurrency': self.config.concurrency
            }
        }
        
        if self._sender:
            stats['sender'] = self._sender.get_stats()
        
        if self._rotation_manager:
            stats['rotation'] = self._rotation_manager.get_statistics()
        
        return stats
    
    async def close(self):
        """Clean up resources."""
        if self._retry_queue:
            await self._retry_queue.stop()
        
        await self.smtp_service.close()
        self._sender = None


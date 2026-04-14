"""Campaign service for managing email campaigns."""

import asyncio
import csv
import logging
import os
import signal
from typing import Dict, Any, Optional, List, Callable, Awaitable, Iterator
from datetime import datetime, UTC
from dataclasses import dataclass

from ..data.database import get_session_direct, init_db
from ..data.repositories import (
    CampaignRepository
)
from ..data.models import (
    Campaign, CampaignStatus,
    EmailLog, EmailStatus
)
from ..utils.async_io import AsyncFileLogger
from ..utils.validation import is_valid_email
from .email_service import EmailService, EmailConfig
from .smtp_service import SMTPService
from .bounce_service import BounceService

logger = logging.getLogger(__name__)


@dataclass 
class CampaignConfig:
    """Campaign configuration from YAML."""
    name: str
    description: str = ""
    
    # Email settings
    subject: str = ""
    subjects: Optional[List[str]] = None
    from_email: str = ""
    from_name: str = ""
    from_names: Optional[List[str]] = None
    from_emails: Optional[List[str]] = None
    reply_to: str = ""
    
    # Template
    template_path: str = ""
    templates: Optional[List[str]] = None
    
    # Recipients
    recipients_path: str = ""
    email_column: str = "email"
    validate_emails: bool = True
    deduplicate: bool = True
    
    # SMTP
    smtp_configs: Optional[List[Dict[str, Any]]] = None
    smtp_rotation: str = "weighted"
    
    # Sending
    dry_run: bool = False
    concurrency: int = 50
    chunk_size: int = 1000
    pause_between_chunks: int = 0
    rate_per_minute: int = 0
    rate_per_hour: int = 0
    
    # Features
    enable_qr_code: bool = False
    send_as_image: bool = False
    convert_attachment: bool = False
    attachment_type: Optional[str] = None
    attachment_path: Optional[str] = None
    
    # Links
    links: Optional[List[str]] = None
    
    # Static placeholders
    placeholders: Optional[Dict[str, str]] = None
    placeholders_path: str = ""


class CampaignService:
    """Service for managing and executing email campaigns."""
    
    def __init__(self):
        self.smtp_service = SMTPService()
        self.email_service: Optional[EmailService] = None
        self.bounce_service: Optional[BounceService] = None
        self.config: Optional[CampaignConfig] = None
        self._current_campaign: Optional[Campaign] = None
        self._running = False
        self._paused = False
        self._shutdown_event = asyncio.Event()
        
        # Register signal handlers for graceful shutdown
        self._setup_signal_handlers()
    
    def _setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown."""
        try:
            loop = asyncio.get_event_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, self._handle_shutdown_signal)
        except (RuntimeError, NotImplementedError):
            # Windows or no event loop yet
            pass
    
    def _handle_shutdown_signal(self):
        """Handle shutdown signal gracefully."""
        logger.info("Received shutdown signal, stopping gracefully...")
        self._running = False
        self._shutdown_event.set()
    
    def initialize(self):
        """Initialize database and services."""
        init_db()
        self.bounce_service = BounceService()
        logger.info("Campaign service initialized")
    
    def load_config(self, config: CampaignConfig):
        """Load campaign configuration."""
        from .identity_service import IdentityService
        from .settings_service import SettingsService

        # Apply Global Settings
        # Only override if campaign config doesn't specify strict limits (0 usually means unlimited or default)
        # But here 0 might mean "use system default" or "unlimited". 
        # For safety in this system, we assume 0 means "inherit global default".
        global_settings = SettingsService.get_settings()
        
        if config.rate_per_hour <= 0:
            config.rate_per_hour = global_settings.hourly_limit
            
        # If rate_per_minute is also 0, we can approximate or leave it to token bucket logic
        # But let's leave it as is, rate limiter handles per-hour fine.

        # Apply Identity Defaults
        # If no "From" identity specified at all, use the pool
        if not config.from_email and not config.from_emails:
            active_emails = IdentityService.get_emails(active_only=True)
            if active_emails:
                if len(active_emails) == 1:
                    config.from_email = active_emails[0].email
                else:
                    # Enable rotation
                    config.from_emails = [e.email for e in active_emails]
                    # Set a default for single-send contexts
                    config.from_email = active_emails[0].email
                    logger.info(f"Using {len(active_emails)} From-Emails from identity pool")

        if not config.from_name and not config.from_names:
            active_names = IdentityService.get_names(active_only=True)
            if active_names:
                if len(active_names) == 1:
                    config.from_name = active_names[0].name
                else:
                    config.from_names = [n.name for n in active_names]
                    config.from_name = active_names[0].name
                    logger.info(f"Using {len(active_names)} Sender Names from identity pool")

        if not config.reply_to and global_settings.default_reply_to:
            config.reply_to = global_settings.default_reply_to

        self.config = config
        
        # Load SMTP servers
        if config.smtp_configs:
            self.smtp_service.load_from_config(config.smtp_configs)
        else:
            self.smtp_service.load_from_database()
        
        # Initialize email service
        self.email_service = EmailService(self.smtp_service)
        self.email_service.configure(EmailConfig(
            subject=config.subject,
            from_email=config.from_email,
            from_name=config.from_name,
            reply_to=config.reply_to,
            template_path=config.template_path,
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
            links=config.links
        ))
        
        # Add static placeholders
        if config.placeholders:
            for key, value in config.placeholders.items():
                self.email_service._template_engine.add_static_placeholder(key, value)
        
        logger.info(f"Loaded campaign config: {config.name}")
    
    def create_campaign(self, config: CampaignConfig) -> Campaign:
        """Create a new campaign in database."""
        session = get_session_direct()
        try:
            campaign = Campaign(
                name=config.name,
                description=config.description,
                status=CampaignStatus.DRAFT,
                from_email=config.from_email,
                from_name=config.from_name,
                reply_to=config.reply_to,
                subjects=config.subjects or [config.subject],
                placeholders=config.placeholders,
                chunk_size=config.chunk_size,
                concurrency=config.concurrency,
                rate_per_minute=config.rate_per_minute,
                rate_per_hour=config.rate_per_hour,
                enable_qr_code=config.enable_qr_code,
                convert_to_image=config.send_as_image,
                smtp_rotation_strategy=config.smtp_rotation,
                settings={'links': config.links} if config.links else {}
            )
            
            repo = CampaignRepository(session)
            campaign = repo.create(campaign)
            
            logger.info(f"Created campaign: {campaign.id} - {campaign.name}")
            return campaign
            
        finally:
            session.close()
    
    def load_recipients_from_csv(
        self,
        csv_path: str,
        email_column: str = 'email',
        validate: bool = True,
        deduplicate: bool = True
    ) -> Iterator[Dict[str, Any]]:
        """
        Load recipients from CSV file as a generator (streaming).
        
        Args:
            csv_path: Path to CSV file
            email_column: Column name containing email addresses
            validate: Validate email format
            deduplicate: Remove duplicates (requires keeping a set in memory)
            
        Returns:
            Iterator of recipient dicts
        """
        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"CSV file not found: {csv_path}")
        
        # Note: Deduplication still requires memory proportional to unique email count.
        # If memory is critical, we might need Bloom filters or disk-based dedup.
        seen_emails = set()
        
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            
            # Smart column detection
            fieldnames = reader.fieldnames or []
            target_column = email_column
            
            if email_column not in fieldnames:
                # Try case-insensitive match
                lower_fieldnames = {f.lower(): f for f in fieldnames}
                if email_column.lower() in lower_fieldnames:
                    target_column = lower_fieldnames[email_column.lower()]
                    logger.info(f"Using column '{target_column}' for '{email_column}' (case-insensitive match)")
                else:
                    logger.warning(f"Email column '{email_column}' not found in CSV. Available: {fieldnames}")
            
            for row in reader:
                email = row.get(target_column, '').strip().lower()
                
                if not email:
                    continue
                
                # Deduplicate
                if deduplicate:
                    if email in seen_emails:
                        continue
                    seen_emails.add(email)
                
                # Validate email format using simple check or email-validator
                if validate:
                    if not is_valid_email(email):
                        continue
                
                # Build recipient dict
                recipient = {'email': email}
                for key, value in row.items():
                    if key != email_column:
                        recipient[key] = value
                
                yield recipient
        
        logger.info(f"Finished streaming recipients from {csv_path}")
    
    def load_recipients_from_text(
        self,
        txt_path: str,
        validate: bool = True,
        deduplicate: bool = True
    ) -> Iterator[Dict[str, Any]]:
        """Load recipients from text file (one email per line) as generator."""
        if not os.path.exists(txt_path):
            raise FileNotFoundError(f"Text file not found: {txt_path}")
        
        seen_emails = set()
        
        with open(txt_path, 'r', encoding='utf-8') as f:
            for line in f:
                email = line.strip().lower()
                
                if not email or email.startswith('#'):
                    continue
                
                if validate and not is_valid_email(email):
                    continue
                
                if deduplicate:
                    if email in seen_emails:
                        continue
                    seen_emails.add(email)
                
                yield {'email': email}
        
        logger.info(f"Finished streaming recipients from {txt_path}")
    
    async def load_recipients_async(
        self,
        path: str,
        validate: bool = True,
        deduplicate: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Load recipients asynchronously (runs in thread executor).
        
        Args:
            path: Path to CSV or Text file
            validate: Validate email format
            deduplicate: Remove duplicates
            
        Returns:
            List of recipient dicts
        """
        def _load():
            if path.lower().endswith('.csv'):
                return list(self.load_recipients_from_csv(path, validate=validate, deduplicate=deduplicate))
            else:
                return list(self.load_recipients_from_text(path, validate=validate, deduplicate=deduplicate))
        
        return await asyncio.to_thread(_load)

    def iterate_recipients(
        self, 
        recipients: Iterator[Dict[str, Any]], 
        chunk_size: int = 1000
    ) -> Iterator[List[Dict[str, Any]]]:
        """Iterate through recipients in chunks."""
        # Handle both list and iterator
        chunk = []
        for recipient in recipients:
            chunk.append(recipient)
            if len(chunk) >= chunk_size:
                yield chunk
                chunk = []
        
        if chunk:
            yield chunk
    
    async def run_campaign(
        self,
        recipients: List[Dict[str, Any]],
        progress_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
        log_path: str = "logs"
    ) -> Dict[str, Any]:
        """
        Execute campaign with all recipients.
        
        Args:
            recipients: List of recipient dicts
            progress_callback: Async callback for progress updates
            log_path: Path for log files
            
        Returns:
            Campaign statistics
        """
        if not self.email_service:
            raise RuntimeError("Email service not configured")
        
        self._running = True
        self._paused = False
        self._shutdown_event.clear()
        
        os.makedirs(log_path, exist_ok=True)
        
        # If recipients is a list, we know the total.
        # If it's an iterator, we might not know unless we counted first.
        # Assuming for now caller handles counting if they need progress bar accuracy.
        total_count = len(recipients) if hasattr(recipients, '__len__') else 0
        
        total_stats = {
            'total': total_count,
            'sent': 0,
            'failed': 0,
            'chunks_processed': 0,
            'start_time': datetime.now(UTC).isoformat()
        }
        
        # Use async file loggers for better performance
        success_log_path = os.path.join(log_path, 'success-emails.txt')
        failed_log_path = os.path.join(log_path, 'failed-emails.txt')
        
        async with AsyncFileLogger(success_log_path) as success_logger, \
                   AsyncFileLogger(failed_log_path) as failed_logger:
            
            session = get_session_direct()
            
            try:
                chunk_size = self.config.chunk_size if self.config else 1000
                pause = self.config.pause_between_chunks if self.config else 0
                
                campaign_id = self._current_campaign.id if self._current_campaign else None
                
                for chunk_num, chunk in enumerate(self.iterate_recipients(recipients, chunk_size)):
                    # Check for shutdown
                    if not self._running or self._shutdown_event.is_set():
                        logger.info("Campaign stopped")
                        break
                    
                    # Handle pause
                    while self._paused and self._running:
                        await asyncio.sleep(1)
                    
                    logger.info(f"Processing chunk {chunk_num + 1} ({len(chunk)} recipients)")
                    
                    # Send chunk
                    result = await self.email_service.send_bulk(
                        recipients=chunk,
                        progress_callback=progress_callback
                    )
                    
                    # Log results asynchronously and to DB
                    db_logs = []
                    
                    for email_result in result.results:
                        if email_result.success:
                            await success_logger.log_success(email_result.recipient)
                            total_stats['sent'] += 1
                            
                            db_logs.append(EmailLog(
                                campaign_id=campaign_id,
                                recipient_email=email_result.recipient,
                                status=EmailStatus.SENT,
                                sent_at=datetime.now(UTC),
                                subject=self.config.subject if self.config else "",
                                from_email=self.config.from_email if self.config else "",
                                smtp_server_name=email_result.smtp_server
                            ))
                        else:
                            await failed_logger.log_failure(
                                email_result.recipient,
                                email_result.error or 'Unknown error'
                            )
                            total_stats['failed'] += 1

                            db_logs.append(EmailLog(
                                campaign_id=campaign_id,
                                recipient_email=email_result.recipient,
                                status=EmailStatus.FAILED,
                                failed_at=datetime.now(UTC),
                                subject=self.config.subject if self.config else "",
                                from_email=self.config.from_email if self.config else "",
                                error_message=email_result.error,
                                error_type=email_result.error_type
                            ))
                    
                    # Batch insert to DB
                    if db_logs:
                        # Todo: Use bulk_save_objects or add a valid batch method to BaseRepository
                        # Using loop for now as BaseRepository.create commits one by one if not careful,
                        # but specialized add_all is better. 
                        # Ideally: log_repo.bulk_create(db_logs)
                        session.add_all(db_logs)
                        session.commit()

                    total_stats['chunks_processed'] += 1
                    
                    # Pause between chunks
                    if pause > 0 and chunk_num < (len(recipients) // chunk_size):
                        logger.info(f"Pausing for {pause} seconds...")
                        try:
                            await asyncio.wait_for(
                                self._shutdown_event.wait(),
                                timeout=pause
                            )
                            # If we get here, shutdown was requested
                            break
                        except asyncio.TimeoutError:
                            # Normal case - timeout expired, continue
                            pass
                
                total_stats['end_time'] = datetime.now(UTC).isoformat()
                total_stats['success_rate'] = round(
                    total_stats['sent'] / total_stats['total'] * 100, 2
                ) if total_stats['total'] > 0 else 0
                
                return total_stats
                
            finally:
                session.close()
                self._running = False
    
    def pause(self):
        """Pause campaign execution."""
        self._paused = True
        logger.info("Campaign paused")
    
    def resume(self):
        """Resume campaign execution."""
        self._paused = False
        logger.info("Campaign resumed")
    
    def stop(self):
        """Stop campaign execution."""
        self._running = False
        self._shutdown_event.set()
        logger.info("Campaign stop requested")
    
    def get_campaign_stats(self, campaign_id: int = None) -> Dict[str, Any]:
        """Get campaign statistics."""
        if self.email_service:
            return self.email_service.get_statistics()
        return {}
    
    def list_campaigns(self, limit: int = 20) -> List[Campaign]:
        """List recent campaigns."""
        session = get_session_direct()
        try:
            repo = CampaignRepository(session)
            return repo.get_recent(limit)
        finally:
            session.close()
    
    async def close(self):
        """Clean up resources."""
        self._running = False
        self._shutdown_event.set()
        
        if self.email_service:
            await self.email_service.close()


def load_campaign_from_yaml(yaml_path: str) -> CampaignConfig:
    """
    Load campaign configuration from YAML file.
    
    Args:
        yaml_path: Path to YAML configuration file
        
    Returns:
        CampaignConfig instance
    """
    import yaml
    
    with open(yaml_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    
    # Extract sections
    campaign = data.get('campaign', {})
    email = data.get('email', {})
    template = data.get('template', {})
    recipients = data.get('recipients', {})
    smtp = data.get('smtp_providers', data.get('smtp', []))
    sending = data.get('sending', {})
    features = data.get('features', {})
    placeholders = data.get('placeholders', {}).get('static', {})
    placeholders_path = data.get('placeholders', {}).get('path', '')
    
    return CampaignConfig(
        name=campaign.get('name', 'Unnamed Campaign'),
        description=campaign.get('description', ''),
        
        subject=email.get('subject', email.get('subjects', [''])[0] if email.get('subjects') else ''),
        subjects=[s.get('template', s) if isinstance(s, dict) else s for s in email.get('subjects', [])],
        from_email=email.get('from_email', ''),
        from_name=email.get('from_name', ''),
        from_names=email.get('from_names', []),
        from_emails=email.get('from_emails', []),
        reply_to=email.get('reply_to', ''),
        
        template_path=template.get('html', template.get('path', '')),
        templates=template.get('variants', []),
        
        recipients_path=recipients.get('source', recipients.get('path', '')),
        email_column=recipients.get('email_column', 'email'),
        validate_emails=recipients.get('validate', True),
        deduplicate=recipients.get('deduplicate', True),
        
        smtp_configs=smtp if isinstance(smtp, list) else [smtp],
        smtp_rotation=data.get('smtp_rotation', {}).get('strategy', 'weighted'),
        
        dry_run=sending.get('dry_run', data.get('dry_run', False)),
        concurrency=sending.get('concurrency', 50),
        chunk_size=sending.get('chunk_size', 1000),
        pause_between_chunks=sending.get('pause_between_chunks', 0),
        rate_per_minute=sending.get('rate_per_minute', 0),
        rate_per_hour=sending.get('rate_per_hour', 0),
        
        enable_qr_code=features.get('qr_codes', False),
        send_as_image=features.get('send_as_image', False),
        convert_attachment=features.get('convert_attachment', False),
        attachment_type=features.get('attachment_type'),
        attachment_path=features.get('attachment_path'),
        
        links=data.get('links', []),
        
        placeholders=placeholders,
        placeholders_path=placeholders_path
    )

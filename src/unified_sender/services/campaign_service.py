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
    CampaignRepository, 
    SMTPRepository, 
    TemplateRepository,
    RecipientRepository,
    RecipientListRepository
)
from ..data.models import (
    Campaign, CampaignStatus, CampaignType,
    RecipientList, Recipient, RecipientStatus,
    Template, SMTPServer, EmailLog, EmailStatus
)
from ..engine.async_sender import BulkSendResult
from ..utils.async_io import AsyncFileLogger
from ..utils.validation import validate_email, is_valid_email
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
    reply_to: str = ""
    
    # Template
    template_path: str = ""
    templates: Optional[List[str]] = None
    
    # Recipients
    recipients_path: str = ""
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
    attachment_type: Optional[str] = None
    attachment_path: Optional[str] = None
    
    # Static placeholders
    placeholders: Optional[Dict[str, str]] = None


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
            dry_run=config.dry_run,
            concurrency=config.concurrency,
            rate_per_minute=config.rate_per_minute,
            rate_per_hour=config.rate_per_hour,
            enable_qr_code=config.enable_qr_code,
            send_as_image=config.send_as_image,
            attachment_type=config.attachment_type,
            attachment_path=config.attachment_path,
            subjects=config.subjects,
            from_names=config.from_names,
            templates=config.templates
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
                convert_to_image=config.send_as_image
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
    ) -> List[Dict[str, Any]]:
        """
        Load recipients from CSV file.
        
        Args:
            csv_path: Path to CSV file
            email_column: Column name containing email addresses
            validate: Validate email format
            deduplicate: Remove duplicates
            
        Returns:
            List of recipient dicts
        """
        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"CSV file not found: {csv_path}")
        
        recipients = []
        seen_emails = set()
        invalid_count = 0
        
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            
            for row in reader:
                email = row.get(email_column, '').strip().lower()
                
                if not email:
                    continue
                
                # Validate email format using email-validator
                if validate:
                    if not is_valid_email(email):
                        logger.debug(f"Invalid email format: {email}")
                        invalid_count += 1
                        continue
                
                # Deduplicate
                if deduplicate:
                    if email in seen_emails:
                        continue
                    seen_emails.add(email)
                
                # Build recipient dict
                recipient = {'email': email}
                for key, value in row.items():
                    if key != email_column:
                        recipient[key] = value
                
                recipients.append(recipient)
        
        logger.info(f"Loaded {len(recipients)} recipients from {csv_path} ({invalid_count} invalid)")
        return recipients
    
    def load_recipients_from_text(
        self,
        txt_path: str,
        validate: bool = True,
        deduplicate: bool = True
    ) -> List[Dict[str, Any]]:
        """Load recipients from text file (one email per line)."""
        if not os.path.exists(txt_path):
            raise FileNotFoundError(f"Text file not found: {txt_path}")
        
        recipients = []
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
                
                recipients.append({'email': email})
        
        logger.info(f"Loaded {len(recipients)} recipients from {txt_path}")
        return recipients
    
    def iterate_recipients(
        self, 
        recipients: List[Dict[str, Any]], 
        chunk_size: int = 1000
    ) -> Iterator[List[Dict[str, Any]]]:
        """Iterate through recipients in chunks."""
        for i in range(0, len(recipients), chunk_size):
            yield recipients[i:i + chunk_size]
    
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
        
        total_stats = {
            'total': len(recipients),
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
            
            try:
                chunk_size = self.config.chunk_size if self.config else 1000
                pause = self.config.pause_between_chunks if self.config else 0
                
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
                    
                    # Log results asynchronously
                    for email_result in result.results:
                        if email_result.success:
                            await success_logger.log_success(email_result.recipient)
                            total_stats['sent'] += 1
                        else:
                            await failed_logger.log_failure(
                                email_result.recipient,
                                email_result.error or 'Unknown error'
                            )
                            total_stats['failed'] += 1
                    
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
    
    return CampaignConfig(
        name=campaign.get('name', 'Unnamed Campaign'),
        description=campaign.get('description', ''),
        
        subject=email.get('subject', email.get('subjects', [''])[0] if email.get('subjects') else ''),
        subjects=[s.get('template', s) if isinstance(s, dict) else s for s in email.get('subjects', [])],
        from_email=email.get('from_email', ''),
        from_name=email.get('from_name', ''),
        from_names=email.get('from_names', []),
        reply_to=email.get('reply_to', ''),
        
        template_path=template.get('html', template.get('path', '')),
        templates=template.get('variants', []),
        
        recipients_path=recipients.get('source', recipients.get('path', '')),
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
        attachment_type=features.get('attachment_type'),
        attachment_path=features.get('attachment_path'),
        
        placeholders=placeholders
    )

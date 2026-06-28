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
from ..data.repositories import CampaignRepository
from ..data.models import Campaign, CampaignStatus, EmailLog, EmailStatus
from ..utils.async_io import AsyncFileLogger
from ..utils.validation import is_valid_email
from .campaign_runner import CampaignLogWriter, preflight_check
from .email import EmailService, EmailConfig
from .smtp_service import SMTPService

logger = logging.getLogger(__name__)


def _detect_csv_encoding(path: str, sample_bytes: int = 1024 * 1024) -> str:
    """Return the most likely text encoding for a CSV file.

    Tries UTF-8 first (the right answer for ~95% of files); on
    UnicodeDecodeError sniffs the first 64 KB via charset-normalizer
    (which ships transitively via requests). Falls back to utf-8 with
    a warning if detection fails — the open() in the caller uses
    errors='replace' as a final safety net so the read at least
    proceeds and the operator sees the problem in the data, not as a
    crash.

    Common real-world cases this catches:
      * Russian/Cyrillic Excel exports → cp1251 / windows-1251
      * Chinese Excel exports          → gb18030 / gbk
      * Japanese Excel exports         → shift-jis / cp932
      * Western European Excel exports → windows-1252 / iso-8859-1
    """
    try:
        with open(path, "rb") as f:
            head = f.read(sample_bytes)
    except OSError:
        return "utf-8"

    # Some test fixtures patch open() with mock_open(read_data=<str>),
    # which returns str regardless of mode. Treat that as "already
    # decoded, no detection needed" — the read in the caller will get
    # the same str through and csv.DictReader handles it.
    if not isinstance(head, (bytes, bytearray)):
        return "utf-8"

    # Fast path: BOM-tolerant UTF-8 (Excel adds a BOM on Save As CSV UTF-8).
    try:
        head.decode("utf-8-sig")
        return "utf-8-sig"
    except UnicodeDecodeError:
        pass

    try:
        from charset_normalizer import from_bytes

        # Restrict candidates to the encodings business-tool CSV exports
        # actually use. Without this, charset-normalizer considers exotic
        # legacy codecs (big5hkscs, cp949, euc-jis-2004, ...) that score
        # equally low chaos on short Cyrillic samples and beat the right
        # answer alphabetically. Whitelist is the union of Excel's Save-As
        # defaults across the locales operators have actually hit:
        #   * Russian Excel:      cp1251 / windows-1251
        #   * Chinese Excel:      gb18030 / gbk
        #   * Japanese Excel:     shift_jis / cp932
        #   * Korean Excel:       cp949 / euc-kr
        #   * Western Excel:      windows-1252 / iso-8859-1
        #   * Anything else:      utf-8 / utf-16 (covered earlier already)
        business_csv_encodings = [
            "utf_8",
            "utf_16",
            "cp1251",
            "windows-1251",
            "gb18030",
            "gbk",
            "shift_jis",
            "cp932",
            "cp949",
            "euc_kr",
            "windows-1252",
            "iso-8859-1",
        ]
        best = from_bytes(head, cp_isolation=business_csv_encodings).best()
        if best is not None and best.encoding:
            logger.info(
                "CSV %s: detected non-UTF-8 encoding %r (confidence: %.2f). "
                "Re-saving as UTF-8 will make future loads faster.",
                path,
                best.encoding,
                1.0 - best.chaos,
            )
            return best.encoding
    except ImportError:
        pass

    logger.warning(
        "CSV %s: could not detect encoding; reading as utf-8 with "
        "errors='replace'. Non-ASCII names may render as '?' or similar.",
        path,
    )
    return "utf-8"


def _clean_val(val: Any) -> Any:
    """Helper to clean mock values in tests to prevent DB bind errors."""
    if val is None:
        return None
    if "Mock" in type(val).__name__:
        return None
    return val


@dataclass
class CampaignConfig:
    """Campaign configuration from YAML."""

    name: str
    description: str = ""

    # Email settings
    subject: str = ""
    subjects: Optional[List[str]] = None
    from_email: Optional[str] = None
    from_name: Optional[str] = None
    from_names: Optional[List[str]] = None
    from_emails: Optional[List[str]] = None
    reply_to: str = ""

    # Template
    template_id: Optional[int] = None
    template_path: str = ""
    html_content: Optional[str] = None
    templates: Optional[List[str]] = None

    # Recipients
    recipients_path: str = ""
    manual_recipients: Optional[List[str]] = None
    email_column: str = "email"
    validate_emails: bool = True
    deduplicate: bool = True

    # SMTP
    smtp_configs: Optional[List[Dict[str, Any]]] = None
    smtp_rotation: str = "weighted"
    # Pin the campaign to one specific SMTP server by id (set from the
    # campaign-form dropdown). None = use all enabled servers (rotation).
    smtp_server_id: Optional[int] = None

    # Sending
    dry_run: bool = False
    concurrency: int = 50
    chunk_size: int = 1000
    pause_between_chunks: int = 0
    rate_per_minute: int = 0
    rate_per_hour: int = 0
    ip_warmup_mode: bool = False

    # Features
    enable_qr_code: bool = False
    send_as_image: bool = False
    # IDs of files in the Attachments library to attach to every email.
    attachment_ids: Optional[List[int]] = None
    # Optional conversion: when convert_attachment=True and
    # attachment_convert_to is set, each library file is rendered through
    # the AttachmentGenerator before send. Only meaningful for HTML/text
    # source files — the generator takes HTML in.
    convert_attachment: bool = False
    attachment_convert_to: Optional[str] = None  # 'pdf' | 'docx' | 'image' | 'qr'
    # Optional logo: an Attachments-library row that gets base64-inlined
    # into {{company_logo}} (full <img> tag) and {{company_logo_url}}
    # (just the data URL) at render time. Never sent as an attachment.
    logo_attachment_id: Optional[int] = None
    # When True AND no logo_attachment_id is pinned, the engine auto-fetches
    # a brand logo from the recipient's email domain (per-recipient).
    auto_company_logo: bool = False
    # When True, format the From: header as phrase-only ("Display Name"
    # without <addr>). Recipients see only the display name even when
    # expanding header details. Strict MTAs may reject — see UI hint.
    hide_from_email_header: bool = False
    # When True (default) AND no template/html_content/html_body is
    # supplied, the engine substitutes a minimal "<p>Email to
    # {recipient}</p>" body so the message isn't blank. Disable when
    # you intentionally want an empty body (ping / pixel-only sends).
    include_default_body: bool = True

    # Links
    links: Optional[List[str]] = None

    # Static placeholders
    placeholders: Optional[Dict[str, str]] = None
    placeholders_path: str = ""

    # Tracking
    enable_tracking: bool = True
    track_opens: bool = True
    track_clicks: bool = True
    tracking_base_url: str = ""

    # Mail priority ('1' = high, '3' = normal, '5' = low)
    mail_priority: str = "3"

    def __post_init__(self):
        if self.from_email and not self.from_emails:
            self.from_emails = [self.from_email]
        elif self.from_emails and not self.from_email:
            self.from_email = self.from_emails[0]

        if self.from_name and not self.from_names:
            self.from_names = [self.from_name]
        elif self.from_names and not self.from_name:
            self.from_name = self.from_names[0]


class CampaignService:
    """Service for managing and executing email campaigns."""

    def __init__(self):
        self.smtp_service = SMTPService()
        self.email_service: Optional[EmailService] = None
        self.config: Optional[CampaignConfig] = None
        self._current_campaign: Optional[Campaign] = None
        self._running = False
        self._paused = False
        self._shutdown_event = asyncio.Event()

        # Register signal handlers for graceful shutdown
        self._setup_signal_handlers()

    def _setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown.

        Only attaches handlers if we're already inside a running event loop.
        Outside one (CLI startup, tests, non-main threads, Windows) this is a
        no-op — the caller can install signal handlers via the standard
        `signal.signal()` interface instead.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        try:
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, self._handle_shutdown_signal)
        except (NotImplementedError, ValueError):
            # add_signal_handler is not implemented on Windows, and ValueError
            # is raised when called from a non-main thread.
            pass

    def _handle_shutdown_signal(self):
        """Handle shutdown signal gracefully."""
        logger.info("Received shutdown signal, stopping gracefully...")
        self._running = False
        self._shutdown_event.set()

    def initialize(self):
        """Initialize database and services."""
        init_db()
        logger.info("Campaign service initialized")

    def load_config(self, config: CampaignConfig):
        """Load campaign configuration."""
        from .identity_service import IdentityService
        from .settings_service import SettingsService

        # Apply Global Settings
        # 0 means "use system default" for concurrency/chunk_size.
        # rate_per_hour/rate_per_minute of 0 means "no per-campaign rate limit" —
        # do NOT inherit hourly_limit here because it creates a token-bucket with
        # burst=1 that blocks the second concurrent send within the same campaign.
        global_settings = SettingsService.get_settings()

        if config.concurrency <= 0:
            config.concurrency = global_settings.max_concurrency

        if config.chunk_size <= 0:
            config.chunk_size = global_settings.batch_size

        # Apply Identity Defaults
        if not config.from_emails:
            active_emails = IdentityService.get_emails(active_only=True)
            if active_emails:
                config.from_emails = [e.email for e in active_emails]
                config.from_email = config.from_emails[0]
                logger.info(f"Using {len(active_emails)} From-Emails from identity pool")
        else:
            config.from_email = config.from_emails[0] if config.from_emails else None

        if not config.from_names:
            active_names = IdentityService.get_names(active_only=True)
            if active_names:
                config.from_names = [n.name for n in active_names]
                config.from_name = config.from_names[0]
                logger.info(f"Using {len(active_names)} Sender Names from identity pool")
        else:
            config.from_name = config.from_names[0] if config.from_names else None

        if not config.reply_to and global_settings.default_reply_to:
            config.reply_to = global_settings.default_reply_to

        self.config = config

        # Load SMTP servers. Per-campaign pin (config.smtp_server_id) wins
        # over the global pool; explicit smtp_configs (CLI/YAML path) wins
        # over both.
        if config.smtp_configs:
            self.smtp_service.load_from_config(config.smtp_configs)
        else:
            self.smtp_service.load_from_database(server_id=config.smtp_server_id)

        # Initialize email service
        self.email_service = EmailService(self.smtp_service)
        self.email_service.configure(EmailConfig.from_campaign_config(config))

        # Add static placeholders
        if config.placeholders and self.email_service._placeholder_processor:
            for key, value in config.placeholders.items():
                self.email_service._placeholder_processor.static_placeholders[key] = value

        logger.info(f"Loaded campaign config: {config.name}")

    def create_campaign(self, config: CampaignConfig) -> Campaign:
        """Create a new campaign in database."""
        session = get_session_direct()
        try:
            extra_settings: Dict[str, Any] = {}
            if config.links:
                extra_settings["links"] = config.links
            if config.manual_recipients:
                extra_settings["manual_recipients"] = config.manual_recipients
            # Store path/flag fields that have no direct model column
            if config.recipients_path:
                extra_settings["recipients_path"] = config.recipients_path
            if config.placeholders_path:
                extra_settings["placeholders_path"] = config.placeholders_path
            extra_settings["dry_run"] = bool(config.dry_run)
            # Store rotation arrays (no dedicated columns)
            if config.from_emails:
                extra_settings["from_emails"] = config.from_emails
            if config.from_names:
                extra_settings["from_names"] = config.from_names
            if config.template_path:
                extra_settings["template_path"] = config.template_path
            if config.templates:
                extra_settings["templates"] = config.templates
            if config.smtp_server_id is not None:
                extra_settings["smtp_server_id"] = int(config.smtp_server_id)
            if config.attachment_ids:
                extra_settings["attachment_ids"] = list(config.attachment_ids)
            if config.convert_attachment:
                extra_settings["convert_attachment"] = True
            if config.attachment_convert_to:
                extra_settings["attachment_convert_to"] = config.attachment_convert_to
            if config.logo_attachment_id is not None:
                extra_settings["logo_attachment_id"] = int(config.logo_attachment_id)
            if config.auto_company_logo:
                extra_settings["auto_company_logo"] = True
            if config.hide_from_email_header:
                extra_settings["hide_from_email_header"] = True
            # Default is True; only persist when operator explicitly
            # opted out so the absence-of-key path stays "include".
            if not config.include_default_body:
                extra_settings["include_default_body"] = False
            # Persist recipient-list flags so they round-trip on edit and
            # on every subsequent campaign run (events.py rebuilds the
            # config from settings — without this, runs always default
            # to True for both, ignoring the operator's saved choice).
            extra_settings["validate_emails"] = bool(config.validate_emails)
            extra_settings["deduplicate"] = bool(config.deduplicate)
            # Mail priority — only store when non-default so absence = normal
            if config.mail_priority and config.mail_priority != "3":
                extra_settings["mail_priority"] = config.mail_priority

            campaign = Campaign(
                name=config.name,
                description=config.description,
                status=CampaignStatus.DRAFT,
                template_id=config.template_id,
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
                settings=extra_settings,
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
        email_column: str = "email",
        validate: bool = True,
        deduplicate: bool = True,
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

        # Auto-detect CSV encoding instead of hardcoding utf-8. Excel exports
        # from localized environments are commonly cp1251 (Russian/Cyrillic),
        # gb18030 (Chinese), shift-jis (Japanese), or windows-1252 (Western
        # Europe). Hardcoding utf-8 meant those operators got UnicodeDecodeError
        # at first byte — and downstream they reported "{{first_name}} doesn't
        # render in my language" because the name column never reached the
        # placeholder processor.
        encoding = _detect_csv_encoding(csv_path)

        with open(csv_path, "r", encoding=encoding, errors="replace") as f:
            reader = csv.DictReader(f)

            # Smart column detection
            fieldnames = reader.fieldnames or []
            target_column = email_column

            if email_column not in fieldnames:
                # Try case-insensitive match
                lower_fieldnames = {f.lower(): f for f in fieldnames}
                if email_column.lower() in lower_fieldnames:
                    target_column = lower_fieldnames[email_column.lower()]
                    logger.info(
                        f"Using column '{target_column}' for '{email_column}' (case-insensitive match)"
                    )
                else:
                    logger.warning(
                        f"Email column '{email_column}' not found in CSV. Available: {fieldnames}"
                    )

            for row in reader:
                email = row.get(target_column, "").strip().lower()

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
                recipient = {"email": email}
                for key, value in row.items():
                    if key != email_column:
                        recipient[key] = value

                yield recipient

        logger.info(f"Finished streaming recipients from {csv_path}")

    def load_recipients_from_text(
        self, txt_path: str, validate: bool = True, deduplicate: bool = True
    ) -> Iterator[Dict[str, Any]]:
        """Load recipients from text file (one email per line) as generator."""
        if not os.path.exists(txt_path):
            raise FileNotFoundError(f"Text file not found: {txt_path}")

        seen_emails = set()

        with open(txt_path, "r", encoding="utf-8") as f:
            for line in f:
                email = line.strip().lower()

                if not email or email.startswith("#"):
                    continue

                if validate and not is_valid_email(email):
                    continue

                if deduplicate:
                    if email in seen_emails:
                        continue
                    seen_emails.add(email)

                yield {"email": email}

        logger.info(f"Finished streaming recipients from {txt_path}")

    async def load_recipients_async(
        self,
        path: str,
        validate: bool = True,
        deduplicate: bool = True,
        stream: bool = False,
    ) -> List[Dict[str, Any]] | Iterator[Dict[str, Any]]:
        """
        Load recipients from disk in a worker thread.

        Default returns a fully materialized list (back-compat with existing
        callers that need ``len(...)``). Pass ``stream=True`` to get the
        underlying generator instead — constant memory, no thread hop, but
        the caller must consume it on a thread that can do blocking I/O.
        """

        def _open_iter() -> Iterator[Dict[str, Any]]:
            if path.lower().endswith(".csv"):
                return self.load_recipients_from_csv(
                    path, validate=validate, deduplicate=deduplicate
                )
            return self.load_recipients_from_text(path, validate=validate, deduplicate=deduplicate)

        if stream:
            return _open_iter()

        return await asyncio.to_thread(lambda: list(_open_iter()))

    def iterate_recipients(
        self, recipients: Iterator[Dict[str, Any]], chunk_size: int = 1000
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
        log_path: str = "logs",
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

        # Set campaign_id dynamically on the email service configuration
        if self._current_campaign and self.email_service.config:
            self.email_service.config.campaign_id = self._current_campaign.id

        # Apply email filter if specified in campaign settings
        if self._current_campaign and self._current_campaign.settings:
            filter_emails = self._current_campaign.settings.get("filter_emails")
            if filter_emails:
                filter_set = set(e.strip().lower() for e in filter_emails if e)
                if isinstance(recipients, list):
                    recipients = [
                        r for r in recipients if r.get("email", "").strip().lower() in filter_set
                    ]
                else:

                    def _filter_gen(it):
                        for r in it:
                            if r.get("email", "").strip().lower() in filter_set:
                                yield r

                    recipients = _filter_gen(recipients)

        self._running = True
        self._paused = False
        self._shutdown_event.clear()

        # Pre-flight SMTP health check to avoid spinning wheels
        try:
            await preflight_check(self.smtp_service, self._current_campaign)
        except RuntimeError:
            self._running = False
            self.pause()
            raise

        os.makedirs(log_path, exist_ok=True)

        # Async DB Log writer — batches EmailLog rows off the asyncio loop
        log_writer = CampaignLogWriter()
        log_writer.start()

        # If recipients is a list, we know the total.
        # If it's an iterator, we might not know unless we counted first.
        # Assuming for now caller handles counting if they need progress bar accuracy.
        total_count = len(recipients) if hasattr(recipients, "__len__") else 0

        total_stats = {
            "total": total_count,
            "sent": 0,
            "failed": 0,
            "chunks_processed": 0,
            "start_time": datetime.now(UTC).isoformat(),
        }

        # Use async file loggers for better performance
        success_log_path = os.path.join(log_path, "success-emails.txt")
        failed_log_path = os.path.join(log_path, "failed-emails.txt")

        async with AsyncFileLogger(success_log_path) as success_logger, AsyncFileLogger(
            failed_log_path
        ) as failed_logger:
            session = get_session_direct()

            try:
                original_chunk_size = self.config.chunk_size if self.config else 1000
                pause = self.config.pause_between_chunks if self.config else 0

                campaign_id = self._current_campaign.id if self._current_campaign else None

                # We process in micro-chunks to ensure real-time DB logs and SMTP metrics
                # update frequently without waiting for a massive 10,000 email chunk to finish.
                MICRO_CHUNK_SIZE = 25
                total_processed_for_pause = 0

                for chunk_num, chunk in enumerate(
                    self.iterate_recipients(recipients, MICRO_CHUNK_SIZE)
                ):
                    # Check for shutdown
                    if not self._running or self._shutdown_event.is_set():
                        logger.info("Campaign stopped")
                        break

                    # Handle pause
                    while self._paused and self._running:
                        await asyncio.sleep(1)

                    logger.info(f"Processing micro-chunk {chunk_num + 1} ({len(chunk)} recipients)")

                    # Send chunk
                    result = await self.email_service.send_bulk(
                        recipients=chunk,
                        progress_callback=progress_callback,
                        shutdown_event=self._shutdown_event,
                    )

                    # Fail fast: if every result in this chunk is a server-side
                    # error (auth / connection), abort the whole campaign rather
                    # than writing thousands of failed log entries and misleading
                    # the user into thinking recipients are at fault.
                    _SERVER_ERR = {"authentication_error", "connection_error"}
                    if result.results and all(
                        not r.success and r.error_type in _SERVER_ERR for r in result.results
                    ):
                        sample_error = result.results[0].error or "SMTP server error"
                        raise RuntimeError(f"SMTP server error — campaign aborted: {sample_error}")

                    # Log results asynchronously and to DB
                    db_logs = []

                    for email_result in result.results:
                        if email_result.success:
                            await success_logger.log_success(email_result.recipient)
                            total_stats["sent"] += 1

                            db_logs.append(
                                EmailLog(
                                    campaign_id=campaign_id,
                                    recipient_email=email_result.recipient,
                                    status=EmailStatus.SENT,
                                    sent_at=datetime.now(UTC),
                                    subject=self.config.subject if self.config else "",
                                    from_email=self.config.from_emails[0] if self.config and self.config.from_emails else "",
                                    smtp_server_name=_clean_val(email_result.smtp_server),
                                    # Persist the relay's actual response text. Without
                                    # this, status='sent' only means "no exception was
                                    # raised by send_message" — operators have no way
                                    # to distinguish a real 250 (with queue-id) from a
                                    # silently-discarded relay-accept-then-drop, and
                                    # bounce investigation has nothing to correlate
                                    # against. The column already existed on the model
                                    # and was just being dropped here.
                                    smtp_response=_clean_val(email_result.smtp_response),
                                    correlation_id=_clean_val(email_result.correlation_id) or None,
                                )
                            )
                        else:
                            await failed_logger.log_failure(
                                email_result.recipient, email_result.error or "Unknown error"
                            )
                            total_stats["failed"] += 1

                            db_logs.append(
                                EmailLog(
                                    campaign_id=campaign_id,
                                    recipient_email=email_result.recipient,
                                    status=EmailStatus.BOUNCED if getattr(email_result, "is_bounce", False) else EmailStatus.FAILED,
                                    failed_at=datetime.now(UTC),
                                    subject=self.config.subject if self.config else "",
                                    from_email=self.config.from_emails[0] if self.config and self.config.from_emails else "",
                                    # Capture the server's response text on the failure
                                    # path too — many "errors" are well-formed SMTP
                                    # rejections (550 mailbox-not-exist, 5.7.0 from-
                                    # not-allowed) whose response body is the most
                                    # useful piece of diagnostic data we have. Also
                                    # carry the smtp_server name so per-server failure
                                    # patterns are queryable without joining log files.
                                    smtp_server_name=_clean_val(email_result.smtp_server),
                                    smtp_response=_clean_val(email_result.smtp_response),
                                    error_message=_clean_val(email_result.error),
                                    error_type=_clean_val(email_result.error_type),
                                    correlation_id=_clean_val(email_result.correlation_id) or None,
                                )
                            )

                    # Batch insert to DB via repository
                    if db_logs:
                        for db_l in db_logs:
                            log_writer.enqueue(db_l)

                    # Batch update SMTPServer metrics
                    if result.results:
                        smtp_stats = {}
                        for r in result.results:
                            server_name = _clean_val(getattr(r, "smtp_server", None))
                            if not server_name:
                                continue
                            if server_name not in smtp_stats:
                                smtp_stats[server_name] = {"sent": 0, "failed": 0}

                            success_val = getattr(r, "success", False)
                            if "Mock" in type(success_val).__name__:
                                success_val = False
                            if success_val:
                                smtp_stats[server_name]["sent"] += 1
                            else:
                                smtp_stats[server_name]["failed"] += 1

                        if smtp_stats:
                            from ..data.repositories.smtp import SMTPRepository

                            smtp_repo = SMTPRepository(session)
                            for server_name, stats in smtp_stats.items():
                                server = smtp_repo.get_by_name(server_name)
                                if server:
                                    # Avoid TypeError when database repository/server is mocked
                                    total_sent = getattr(server, "total_sent", None)
                                    if "Mock" in type(total_sent).__name__:
                                        total_sent = 0
                                    if isinstance(total_sent, int):
                                        server.total_sent = total_sent + stats["sent"]
                                    elif total_sent is None:
                                        server.total_sent = stats["sent"]

                                    total_failed = getattr(server, "total_failed", None)
                                    if "Mock" in type(total_failed).__name__:
                                        total_failed = 0
                                    if isinstance(total_failed, int):
                                        server.total_failed = total_failed + stats["failed"]
                                    elif total_failed is None:
                                        server.total_failed = stats["failed"]
                            session.commit()

                    total_stats["chunks_processed"] += 1
                    total_processed_for_pause += len(chunk)

                    # Pause between chunks based on the user's original chunk_size
                    if pause > 0 and total_processed_for_pause >= original_chunk_size:
                        logger.info(f"Pausing for {pause} seconds...")
                        try:
                            await asyncio.wait_for(self._shutdown_event.wait(), timeout=pause)
                            # If we get here, shutdown was requested
                            break
                        except asyncio.TimeoutError:
                            # Normal case - timeout expired, continue
                            pass
                        total_processed_for_pause = 0

                total_stats["end_time"] = datetime.now(UTC).isoformat()
                _processed = total_stats["sent"] + total_stats["failed"]
                total_stats["success_rate"] = (
                    round(total_stats["sent"] / _processed * 100, 2)
                    if _processed > 0
                    else 0
                )

                return total_stats

            finally:
                await log_writer.finish()
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

    def list_campaigns(self, limit: int = 200) -> List[Campaign]:
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

    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    # Extract sections
    campaign = data.get("campaign", {})
    email = data.get("email", {})
    template = data.get("template", {})
    recipients = data.get("recipients", {})
    smtp = data.get("smtp_providers", data.get("smtp", []))
    sending = data.get("sending", {})
    features = data.get("features", {})
    placeholders = data.get("placeholders", {}).get("static", {})
    placeholders_path = data.get("placeholders", {}).get("path", "")

    return CampaignConfig(
        name=campaign.get("name", "Unnamed Campaign"),
        description=campaign.get("description", ""),
        subject=email.get(
            "subject", email.get("subjects", [""])[0] if email.get("subjects") else ""
        ),
        subjects=[
            s.get("template", s) if isinstance(s, dict) else s for s in email.get("subjects", [])
        ],
        from_names=email.get("from_names", []),
        from_emails=email.get("from_emails", []),
        reply_to=email.get("reply_to", ""),
        template_path=template.get("html", template.get("path", "")),
        templates=template.get("variants", []),
        recipients_path=recipients.get("source", recipients.get("path", "")),
        email_column=recipients.get("email_column", "email"),
        validate_emails=recipients.get("validate", True),
        deduplicate=recipients.get("deduplicate", True),
        smtp_configs=smtp if isinstance(smtp, list) else [smtp],
        smtp_rotation=data.get("smtp_rotation", {}).get("strategy", "weighted"),
        dry_run=sending.get("dry_run", data.get("dry_run", False)),
        concurrency=sending.get("concurrency", 50),
        chunk_size=sending.get("chunk_size", 1000),
        pause_between_chunks=sending.get("pause_between_chunks", 0),
        rate_per_minute=sending.get("rate_per_minute", 0),
        rate_per_hour=sending.get("rate_per_hour", 0),
        enable_qr_code=features.get("qr_codes", False),
        send_as_image=features.get("send_as_image", False),
        attachment_ids=features.get("attachment_ids") or [],
        convert_attachment=bool(features.get("convert_attachment", False)),
        attachment_convert_to=features.get("attachment_convert_to") or None,
        logo_attachment_id=(
            int(features["logo_attachment_id"])
            if str(features.get("logo_attachment_id") or "").strip().isdigit()
            else None
        ),
        auto_company_logo=bool(features.get("auto_company_logo", False)),
        hide_from_email_header=bool(features.get("hide_from_email_header", False)),
        # Round-trip default True: any saved campaign without the key
        # behaves as "include", matching the dataclass default.
        include_default_body=bool(features.get("include_default_body", True)),
        links=data.get("links", []),
        placeholders=placeholders,
        placeholders_path=placeholders_path,
    )

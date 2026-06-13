"""Email service configuration dataclass."""
from dataclasses import dataclass
from typing import Any, List, Optional


@dataclass
class EmailConfig:
    """Email configuration."""

    subject: str = ""
    from_emails: Optional[List[str]] = None
    reply_to: str = ""
    template_path: Optional[str] = None
    placeholders_path: Optional[str] = None
    html_content: Optional[str] = None
    campaign_id: Optional[int] = None

    # Attachments — library only.
    attachment_ids: Optional[List[int]] = None
    # Optional per-campaign conversion of every library file through
    # AttachmentGenerator before send (HTML source → PDF/DOCX/PNG/QR).
    convert_attachment: bool = False
    attachment_convert_to: Optional[str] = None
    # Attachments-library row id to inline as {{company_logo}}.
    logo_attachment_id: Optional[int] = None
    # Auto-fetch brand logo from recipient domain when no pin is set.
    auto_company_logo: bool = False
    # Strip the addr-spec from the From: header so recipients see only
    # the display name. Phrase-only header per RFC 5322 — strict MTAs
    # may reject.
    hide_from_email_header: bool = False
    # Include the "<p>Email to {recipient}</p>" fallback paragraph when
    # no template/html_content/html_body produces a body. Default True
    # preserves historical behavior; disable for pixel-only / ping sends.
    include_default_body: bool = True

    # Features
    enable_qr_code: bool = False
    send_as_image: bool = False

    # Tracking
    enable_tracking: bool = True
    track_opens: bool = True
    track_clicks: bool = True
    tracking_base_url: Optional[str] = None

    # Mail priority (RFC 2156 / MS extensions)
    # '1' = high, '3' = normal (default), '5' = low
    mail_priority: str = "3"

    # Sending options
    dry_run: bool = False
    concurrency: int = 50
    rate_per_minute: int = 0
    rate_per_hour: int = 0
    ip_warmup_mode: bool = False

    # Rotation
    subjects: Optional[List[str]] = None
    from_names: Optional[List[str]] = None
    templates: Optional[List[str]] = None
    links: Optional[List[str]] = None
    rotation_strategy: str = "round_robin"
    from_email: Optional[str] = None
    from_name: Optional[str] = None

    def __post_init__(self):
        if self.from_email and not self.from_emails:
            self.from_emails = [self.from_email]
        elif self.from_emails and not self.from_email:
            self.from_email = self.from_emails[0]

        if self.from_name and not self.from_names:
            self.from_names = [self.from_name]
        elif self.from_names and not self.from_name:
            self.from_name = self.from_names[0]

    @classmethod
    def from_campaign_config(cls, config: "Any") -> "EmailConfig":
        """Build an EmailConfig from a CampaignConfig instance."""
        return cls(
            subject=config.subject,
            reply_to=config.reply_to,
            template_path=config.template_path,
            html_content=config.html_content,
            placeholders_path=config.placeholders_path,
            dry_run=config.dry_run,
            concurrency=config.concurrency,
            rate_per_minute=config.rate_per_minute,
            rate_per_hour=config.rate_per_hour,
            ip_warmup_mode=getattr(config, "ip_warmup_mode", False),
            enable_qr_code=config.enable_qr_code,
            send_as_image=config.send_as_image,
            attachment_ids=getattr(config, "attachment_ids", None) or [],
            convert_attachment=bool(getattr(config, "convert_attachment", False)),
            attachment_convert_to=getattr(config, "attachment_convert_to", None),
            logo_attachment_id=getattr(config, "logo_attachment_id", None),
            auto_company_logo=bool(getattr(config, "auto_company_logo", False)),
            hide_from_email_header=bool(getattr(config, "hide_from_email_header", False)),
            include_default_body=bool(getattr(config, "include_default_body", True)),
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
            mail_priority=getattr(config, "mail_priority", "3") or "3",
            campaign_id=getattr(config, "campaign_id", None),
        )

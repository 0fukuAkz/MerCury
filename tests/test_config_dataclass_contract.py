"""Snapshot tests pinning the contract between MerCury's overlapping config dataclasses.

There are currently four config dataclasses with significant overlap:
    - SMTPServerConfig (engine.connection_pool)
    - CampaignConfig    (services.campaign_service)
    - EmailConfig       (services.email_service)
    - SMTPConfig        (CLI YAML loader, lives inside CampaignConfig)

These tests document the field-mapping contract so a future refactor that
collapses them into a smaller surface can verify nothing was silently dropped.

If any of these tests fail after a refactor, the refactor lost a field on the
way through one of the layers — fix the field-mapping, don't relax the test.
"""

from dataclasses import fields

from mercury.engine.connection_pool import SMTPServerConfig
from mercury.services.campaign_service import CampaignConfig
from mercury.services.email_service import EmailConfig


# Frozen field lists: any addition or removal in the source dataclass forces
# the test to be updated, which forces the contract owner to think about
# whether the change should propagate through every layer.

CAMPAIGN_CONFIG_FIELDS = frozenset({
    'name', 'description',
    'subject', 'subjects', 'from_email', 'from_name',
    'from_names', 'from_emails', 'reply_to',
    'template_id', 'template_path', 'html_content', 'templates',
    'recipients_path', 'manual_recipients', 'email_column',
    'validate_emails', 'deduplicate',
    'smtp_configs', 'smtp_rotation',
    'dry_run', 'concurrency', 'chunk_size', 'pause_between_chunks',
    'rate_per_minute', 'rate_per_hour',
    'enable_qr_code', 'send_as_image', 'convert_attachment',
    'attachment_type', 'attachment_path',
    'links',
    'placeholders', 'placeholders_path',
    'enable_tracking', 'track_opens', 'track_clicks', 'tracking_base_url',
})

EMAIL_CONFIG_FIELDS = frozenset({
    'subject', 'from_email', 'from_name', 'from_emails', 'reply_to',
    'template_path', 'placeholders_path', 'html_content',
    'attachment_path', 'attachment_type',
    'enable_qr_code', 'send_as_image', 'convert_attachment',
    'enable_tracking', 'track_opens', 'track_clicks', 'tracking_base_url',
    'dry_run', 'concurrency', 'rate_per_minute', 'rate_per_hour',
    'subjects', 'from_names', 'templates', 'links', 'rotation_strategy',
})

SMTP_SERVER_CONFIG_FIELDS = frozenset({
    'name', 'host', 'port', 'username', 'password',
    'use_tls', 'use_ssl', 'use_auth', 'timeout',
    'from_email', 'from_name',
    'weight', 'priority',
    'max_per_minute', 'max_per_hour',
    # Circuit breaker tuning (added in earlier hardening pass)
    'cb_failure_threshold', 'cb_success_threshold',
    'cb_timeout_seconds', 'cb_monitor_window_seconds',
    # Mutable runtime state — a future refactor should split these out into
    # SMTPServerStats. Pinned here so we notice when that happens.
    'circuit_breaker',
    'current_minute_count', 'current_hour_count',
    'total_sent', 'total_failures', 'consecutive_failures',
    'last_minute_reset', 'last_hour_reset',
})


def _names(cls):
    return frozenset(f.name for f in fields(cls))


def test_campaign_config_fields_pinned():
    assert _names(CampaignConfig) == CAMPAIGN_CONFIG_FIELDS, (
        "CampaignConfig fields drifted. Update CAMPAIGN_CONFIG_FIELDS *and* "
        "verify the new/removed field is propagated through "
        "EmailConfig.from_campaign_config and the API/YAML/CLI loaders."
    )


def test_email_config_fields_pinned():
    assert _names(EmailConfig) == EMAIL_CONFIG_FIELDS, (
        "EmailConfig fields drifted. Update EMAIL_CONFIG_FIELDS and verify "
        "EmailConfig.from_campaign_config still copies every relevant field."
    )


def test_smtp_server_config_fields_pinned():
    assert _names(SMTPServerConfig) == SMTP_SERVER_CONFIG_FIELDS, (
        "SMTPServerConfig fields drifted. Update SMTP_SERVER_CONFIG_FIELDS "
        "and verify the SMTPServer DB model + repository sync the new field."
    )


def test_email_config_from_campaign_config_round_trip():
    """Every EmailConfig field that has a CampaignConfig counterpart must be copied.

    This is the primary safety net for the planned config-collapse refactor.
    If you add a field to both CampaignConfig and EmailConfig, you must also
    add it to from_campaign_config — this test will fail until you do.
    """
    cc = CampaignConfig(
        name='spec',
        subject='S', subjects=['S1'],
        from_email='a@b.c', from_name='A',
        from_emails=['a@b.c', 'b@b.c'], from_names=['A', 'B'],
        reply_to='r@b.c',
        template_path='t.html', templates=['t1.html'],
        html_content='<p>hi</p>',
        placeholders_path='p.yaml',
        dry_run=True, concurrency=7,
        rate_per_minute=11, rate_per_hour=22,
        smtp_rotation='priority',
        enable_qr_code=True, send_as_image=True, convert_attachment=True,
        attachment_type='pdf', attachment_path='a.pdf',
        links=['https://x'],
        enable_tracking=False, track_opens=False, track_clicks=False,
        tracking_base_url='https://t.example',
    )
    ec = EmailConfig.from_campaign_config(cc)

    # Direct field copies
    assert ec.subject == cc.subject
    assert ec.subjects == cc.subjects
    assert ec.from_email == cc.from_email
    assert ec.from_name == cc.from_name
    assert ec.from_emails == cc.from_emails
    assert ec.from_names == cc.from_names
    assert ec.reply_to == cc.reply_to
    assert ec.template_path == cc.template_path
    assert ec.templates == cc.templates
    assert ec.html_content == cc.html_content
    assert ec.placeholders_path == cc.placeholders_path
    assert ec.dry_run == cc.dry_run
    assert ec.concurrency == cc.concurrency
    assert ec.rate_per_minute == cc.rate_per_minute
    assert ec.rate_per_hour == cc.rate_per_hour
    assert ec.enable_qr_code == cc.enable_qr_code
    assert ec.send_as_image == cc.send_as_image
    assert ec.convert_attachment == cc.convert_attachment
    assert ec.attachment_type == cc.attachment_type
    assert ec.attachment_path == cc.attachment_path
    assert ec.links == cc.links
    assert ec.enable_tracking == cc.enable_tracking
    assert ec.track_opens == cc.track_opens
    assert ec.track_clicks == cc.track_clicks
    assert ec.tracking_base_url == cc.tracking_base_url

    # Renamed field
    assert ec.rotation_strategy == cc.smtp_rotation


def test_email_config_tracking_base_url_normalizes_empty_string():
    """from_campaign_config converts empty tracking_base_url to None."""
    cc = CampaignConfig(name='x', tracking_base_url='')
    ec = EmailConfig.from_campaign_config(cc)
    assert ec.tracking_base_url is None

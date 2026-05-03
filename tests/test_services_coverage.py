"""Coverage tests for services - targeting specific missing lines."""

import pytest
import asyncio
import os
import tempfile
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime, UTC, timedelta


# ---------------------------------------------------------------------------
# dead_letter_service - lines 97, 160-179
# ---------------------------------------------------------------------------

class TestDeadLetterServiceCoverage:
    """Cover missing lines in dead_letter_service.py."""

    def _make_service(self):
        from mercury.services.dead_letter_service import DeadLetterService
        repo = MagicMock()
        return DeadLetterService(repository=repo), repo

    def test_get_by_campaign(self):
        """Line 97: get_by_campaign calls repo.get_by_campaign."""
        svc, repo = self._make_service()
        repo.get_by_campaign.return_value = []
        result = svc.get_by_campaign(42)
        repo.get_by_campaign.assert_called_once_with(42)
        assert result == []

    def test_cleanup_resolved_no_old_letters(self):
        """Lines 160-179: cleanup_resolved with no matching records returns 0."""
        svc, repo = self._make_service()

        # session.execute(...).scalars() returns empty list
        mock_scalars = MagicMock()
        mock_scalars.__iter__ = MagicMock(return_value=iter([]))
        mock_execute_result = MagicMock()
        mock_execute_result.scalars.return_value = mock_scalars
        repo.session.execute.return_value = mock_execute_result

        result = svc.cleanup_resolved(days_old=30)
        assert result == 0

    def test_cleanup_resolved_with_old_letters(self):
        """Lines 160-179: cleanup_resolved deletes and returns count."""
        svc, repo = self._make_service()

        letter1 = MagicMock()
        letter2 = MagicMock()

        mock_scalars = MagicMock()
        mock_scalars.__iter__ = MagicMock(return_value=iter([letter1, letter2]))
        mock_execute_result = MagicMock()
        mock_execute_result.scalars.return_value = mock_scalars
        repo.session.execute.return_value = mock_execute_result

        result = svc.cleanup_resolved(days_old=7)
        assert result == 2
        assert repo.delete.call_count == 2

    def test_cleanup_resolved_default_days(self):
        """Lines 160-179: cleanup_resolved uses default 30 days."""
        svc, repo = self._make_service()

        mock_scalars = MagicMock()
        mock_scalars.__iter__ = MagicMock(return_value=iter([]))
        mock_execute_result = MagicMock()
        mock_execute_result.scalars.return_value = mock_scalars
        repo.session.execute.return_value = mock_execute_result

        result = svc.cleanup_resolved()
        assert result == 0


# ---------------------------------------------------------------------------
# bounce_service - bounce categorization and recording
# ---------------------------------------------------------------------------

class TestBounceServiceCoverage:
    """Cover missing lines in bounce_service.py."""

    def test_bounce_record_to_dict(self):
        """Line 46: BounceRecord.to_dict()."""
        from mercury.services.bounce_service import BounceRecord, BounceType, BounceCategory
        record = BounceRecord(
            id="test-id",
            email="user@example.com",
            bounce_type=BounceType.HARD,
            category=BounceCategory.INVALID_ADDRESS,
            timestamp=datetime.now(UTC),
            reason="test reason",
            smtp_code="550",
            campaign_id="camp-1"
        )
        d = record.to_dict()
        assert d['id'] == 'test-id'
        assert d['bounce_type'] == 'hard'
        assert d['category'] == 'invalid_address'
        assert d['smtp_code'] == '550'

    def test_categorize_bounce_smtp_code_5xx(self):
        """Lines 181-185: categorize_bounce with 5xx SMTP codes."""
        from mercury.services.bounce_service import BounceService, BounceType, BounceCategory
        svc = BounceService()

        # 550 -> HARD / INVALID_ADDRESS
        btype, cat = svc.categorize_bounce("550", "some unknown message")
        assert btype == BounceType.HARD
        assert cat == BounceCategory.INVALID_ADDRESS

        # 4xx -> SOFT / TECHNICAL
        btype, cat = svc.categorize_bounce("421", "generic 4xx message")
        assert btype == BounceType.SOFT
        assert cat == BounceCategory.TECHNICAL

    def test_process_unsubscribe(self):
        """Lines 292-311: process_unsubscribe."""
        from mercury.services.bounce_service import BounceService, BounceType
        svc = BounceService()
        record = svc.process_unsubscribe("user@example.com", campaign_id="c1")
        assert record.bounce_type == BounceType.UNSUBSCRIBE
        assert record.email == "user@example.com"


# ---------------------------------------------------------------------------
# campaign_service - lines 116-118, 152-155, 163-165, 174, 206-207
#                    322-341, 360-366, 443-444, 448, 506-516, 548
# ---------------------------------------------------------------------------

class TestCampaignServiceCoverage:
    """Cover missing lines in campaign_service.py."""

    def test_handle_shutdown_signal(self):
        """Lines 116-118: _handle_shutdown_signal sets flags."""
        from mercury.services.campaign_service import CampaignService
        with patch.object(CampaignService, '_setup_signal_handlers'):
            svc = CampaignService()
        svc._running = True
        svc._handle_shutdown_signal()
        assert svc._running is False
        assert svc._shutdown_event.is_set()

    def test_load_config_multiple_from_emails(self):
        """Lines 152-155: load_config with multiple active emails."""
        from mercury.services.campaign_service import CampaignService, CampaignConfig
        with patch.object(CampaignService, '_setup_signal_handlers'):
            svc = CampaignService()

        config = CampaignConfig(name="test", from_email="", from_emails=None)

        mock_email1 = MagicMock()
        mock_email1.email = "sender1@test.com"
        mock_email2 = MagicMock()
        mock_email2.email = "sender2@test.com"

        mock_name1 = MagicMock()
        mock_name1.name = "Name1"
        mock_name2 = MagicMock()
        mock_name2.name = "Name2"

        mock_settings = MagicMock()
        mock_settings.hourly_limit = 1000
        mock_settings.default_reply_to = ""

        with patch('mercury.services.settings_service.SettingsService') as MockSettings, \
             patch('mercury.services.identity_service.IdentityService') as MockIdentity:
            MockSettings.get_settings.return_value = mock_settings
            MockIdentity.get_emails.return_value = [mock_email1, mock_email2]
            MockIdentity.get_names.return_value = [mock_name1, mock_name2]

            svc.smtp_service = MagicMock()
            svc.smtp_service.load_from_database = MagicMock()
            svc.email_service = MagicMock()

            with patch('mercury.services.campaign_service.EmailService') as MockEmailService:
                MockEmailService.return_value = MagicMock()
                svc.load_config(config)

        # Multiple emails triggers rotation path (lines 152-155)
        assert config.from_emails == ["sender1@test.com", "sender2@test.com"]

    def test_load_config_multiple_from_names(self):
        """Lines 163-165: load_config with multiple active names."""
        from mercury.services.campaign_service import CampaignService, CampaignConfig
        with patch.object(CampaignService, '_setup_signal_handlers'):
            svc = CampaignService()

        config = CampaignConfig(name="test", from_email="fixed@test.com", from_name="", from_names=None)

        mock_name1 = MagicMock()
        mock_name1.name = "Name1"
        mock_name2 = MagicMock()
        mock_name2.name = "Name2"

        mock_settings = MagicMock()
        mock_settings.hourly_limit = 0
        mock_settings.default_reply_to = ""

        with patch('mercury.services.settings_service.SettingsService') as MockSettings, \
             patch('mercury.services.identity_service.IdentityService') as MockIdentity:
            MockSettings.get_settings.return_value = mock_settings
            MockIdentity.get_emails.return_value = []
            MockIdentity.get_names.return_value = [mock_name1, mock_name2]

            svc.smtp_service = MagicMock()
            svc.smtp_service.load_from_database = MagicMock()

            with patch('mercury.services.campaign_service.EmailService') as MockEmailService:
                MockEmailService.return_value = MagicMock()
                svc.load_config(config)

        # Multiple names triggers rotation path (lines 163-165)
        assert config.from_names == ["Name1", "Name2"]

    def test_load_config_reply_to_from_global_settings(self):
        """Line 174: load_config applies default_reply_to from global settings."""
        from mercury.services.campaign_service import CampaignService, CampaignConfig
        with patch.object(CampaignService, '_setup_signal_handlers'):
            svc = CampaignService()

        config = CampaignConfig(name="test", from_email="sender@test.com", reply_to="")

        mock_settings = MagicMock()
        mock_settings.hourly_limit = 0
        mock_settings.default_reply_to = "reply@test.com"

        with patch('mercury.services.settings_service.SettingsService') as MockSettings, \
             patch('mercury.services.identity_service.IdentityService') as MockIdentity:
            MockSettings.get_settings.return_value = mock_settings
            MockIdentity.get_emails.return_value = []
            MockIdentity.get_names.return_value = []

            svc.smtp_service = MagicMock()
            svc.smtp_service.load_from_database = MagicMock()

            with patch('mercury.services.campaign_service.EmailService') as MockEmailService:
                MockEmailService.return_value = MagicMock()
                svc.load_config(config)

        assert config.reply_to == "reply@test.com"

    def test_load_config_with_placeholders(self):
        """load_config copies static placeholders into the placeholder processor.

        load_config writes directly into ``email_service._placeholder_processor
        .static_placeholders`` (a dict) rather than calling a method, so the
        assertion has to inspect the dict, not a mocked call.
        """
        from mercury.services.campaign_service import CampaignService, CampaignConfig
        with patch.object(CampaignService, '_setup_signal_handlers'):
            svc = CampaignService()

        config = CampaignConfig(
            name="test",
            from_email="sender@test.com",
            placeholders={"company": "Acme"},
        )

        mock_settings = MagicMock()
        mock_settings.hourly_limit = 0
        mock_settings.default_reply_to = ""

        # Use a real dict for static_placeholders so assignment behaves naturally.
        static_placeholders: dict = {}
        mock_processor = MagicMock()
        mock_processor.static_placeholders = static_placeholders
        mock_email_svc = MagicMock()
        mock_email_svc._placeholder_processor = mock_processor

        with patch('mercury.services.settings_service.SettingsService') as MockSettings, \
             patch('mercury.services.identity_service.IdentityService') as MockIdentity:
            MockSettings.get_settings.return_value = mock_settings
            MockIdentity.get_emails.return_value = []
            MockIdentity.get_names.return_value = []

            svc.smtp_service = MagicMock()
            svc.smtp_service.load_from_database = MagicMock()

            with patch('mercury.services.campaign_service.EmailService', return_value=mock_email_svc):
                svc.load_config(config)

        assert static_placeholders == {"company": "Acme"}

    def test_load_recipients_from_csv_missing_column(self):
        """Lines 322-341: load_recipients_from_csv with case-insensitive column match."""
        from mercury.services.campaign_service import CampaignService
        with patch.object(CampaignService, '_setup_signal_handlers'):
            svc = CampaignService()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as f:
            f.write("Email,name\n")
            f.write("user@example.com,John\n")
            fname = f.name

        try:
            recipients = list(svc.load_recipients_from_csv(fname, email_column='email', validate=False))
            assert len(recipients) == 1
            assert recipients[0]['email'] == 'user@example.com'
        finally:
            os.unlink(fname)

    def test_load_recipients_from_text(self):
        """Lines 360-366: load_recipients_from_text."""
        from mercury.services.campaign_service import CampaignService
        with patch.object(CampaignService, '_setup_signal_handlers'):
            svc = CampaignService()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
            f.write("user1@example.com\n")
            f.write("# comment line\n")
            f.write("user2@example.com\n")
            f.write("invalid-email\n")
            fname = f.name

        try:
            recipients = list(svc.load_recipients_from_text(fname, validate=True))
            emails = [r['email'] for r in recipients]
            assert 'user1@example.com' in emails
            assert 'user2@example.com' in emails
            assert 'invalid-email' not in emails
        finally:
            os.unlink(fname)

    def test_load_recipients_from_text_deduplicate(self):
        """Lines 360-366: deduplication in load_recipients_from_text."""
        from mercury.services.campaign_service import CampaignService
        with patch.object(CampaignService, '_setup_signal_handlers'):
            svc = CampaignService()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
            f.write("dup@example.com\n")
            f.write("dup@example.com\n")
            fname = f.name

        try:
            recipients = list(svc.load_recipients_from_text(fname, validate=False, deduplicate=True))
            assert len(recipients) == 1
        finally:
            os.unlink(fname)

    @pytest.mark.asyncio
    async def test_load_recipients_async_csv(self):
        """Lines 443-444, 448: load_recipients_async for CSV file."""
        from mercury.services.campaign_service import CampaignService
        with patch.object(CampaignService, '_setup_signal_handlers'):
            svc = CampaignService()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as f:
            f.write("email,name\n")
            f.write("user@example.com,Test\n")
            fname = f.name

        try:
            recipients = await svc.load_recipients_async(fname, validate=False)
            assert len(recipients) == 1
        finally:
            os.unlink(fname)

    @pytest.mark.asyncio
    async def test_load_recipients_async_txt(self):
        """Lines 443-444, 448: load_recipients_async for text file."""
        from mercury.services.campaign_service import CampaignService
        with patch.object(CampaignService, '_setup_signal_handlers'):
            svc = CampaignService()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
            f.write("user@example.com\n")
            fname = f.name

        try:
            recipients = await svc.load_recipients_async(fname, validate=False)
            assert len(recipients) == 1
        finally:
            os.unlink(fname)

    def test_iterate_recipients_chunking(self):
        """Lines 506-516: iterate_recipients chunking."""
        from mercury.services.campaign_service import CampaignService
        with patch.object(CampaignService, '_setup_signal_handlers'):
            svc = CampaignService()

        recipients = [{'email': f'u{i}@test.com'} for i in range(25)]
        chunks = list(svc.iterate_recipients(recipients, chunk_size=10))
        assert len(chunks) == 3
        assert len(chunks[0]) == 10
        assert len(chunks[1]) == 10
        assert len(chunks[2]) == 5

    def test_get_campaign_stats_no_email_service(self):
        """Line 548: get_campaign_stats with no email_service returns {}."""
        from mercury.services.campaign_service import CampaignService
        with patch.object(CampaignService, '_setup_signal_handlers'):
            svc = CampaignService()
        svc.email_service = None
        result = svc.get_campaign_stats()
        assert result == {}


# ---------------------------------------------------------------------------
# smtp_service - lines 93, 162-171, 194-195
# ---------------------------------------------------------------------------

class TestSMTPServiceCoverage:
    """Cover missing lines in smtp_service.py."""

    def test_get_connection_pool_no_configs_raises(self):
        """Line 93: get_connection_pool raises if no configs."""
        from mercury.services.smtp_service import SMTPService
        svc = SMTPService()
        with pytest.raises(RuntimeError, match="No SMTP servers configured"):
            svc.get_connection_pool()

    def test_remove_server_found(self):
        """Lines 162-171: remove_server when server exists."""
        from mercury.services.smtp_service import SMTPService
        svc = SMTPService()

        mock_session = MagicMock()
        mock_repo = MagicMock()
        mock_server = MagicMock()
        mock_repo.get_by_name.return_value = mock_server
        mock_repo.delete.return_value = True

        with patch('mercury.services.smtp_service.get_session_direct', return_value=mock_session), \
             patch('mercury.services.smtp_service.SMTPRepository', return_value=mock_repo):
            result = svc.remove_server("test-server")

        assert result is True
        mock_repo.delete.assert_called_once_with(mock_server)

    def test_remove_server_not_found(self):
        """Lines 162-171: remove_server when server not found returns False."""
        from mercury.services.smtp_service import SMTPService
        svc = SMTPService()

        mock_session = MagicMock()
        mock_repo = MagicMock()
        mock_repo.get_by_name.return_value = None

        with patch('mercury.services.smtp_service.get_session_direct', return_value=mock_session), \
             patch('mercury.services.smtp_service.SMTPRepository', return_value=mock_repo):
            result = svc.remove_server("nonexistent-server")

        assert result is False

    @pytest.mark.asyncio
    async def test_close_with_pool(self):
        """Lines 194-195: close() with existing connection pool."""
        from mercury.services.smtp_service import SMTPService
        svc = SMTPService()

        mock_pool = AsyncMock()
        svc._connection_pool = mock_pool

        await svc.close()

        mock_pool.close_all.assert_awaited_once()
        assert svc._connection_pool is None


# ---------------------------------------------------------------------------
# identity_service - lines 146-147, 166
# ---------------------------------------------------------------------------

class TestIdentityServiceCoverage:
    """Cover missing lines in identity_service.py."""

    def test_get_random_identity_tag_filtered_email_fallback(self):
        """Lines 146-147: get_random_identity falls back to all emails when tag filter returns empty."""
        from mercury.services.identity_service import IdentityService

        mock_email = MagicMock()
        mock_email.email = "sender@test.com"
        mock_email.tags = []
        mock_email.use_count = 0
        mock_email.last_used_at = None

        mock_name = MagicMock()
        mock_name.name = "Test Name"
        mock_name.tags = []
        mock_name.use_count = 0
        mock_name.last_used_at = None

        mock_session = MagicMock()
        mock_session.scalars.side_effect = [
            MagicMock(all=MagicMock(return_value=[mock_email])),
            MagicMock(all=MagicMock(return_value=[mock_name])),
        ]
        mock_session.commit = MagicMock()

        with patch('mercury.services.identity_service.get_session_direct', return_value=mock_session):
            email, name = IdentityService.get_random_identity(tag="nonexistent_tag")

        # Falls back to any email/name when tag filter is empty
        assert email == "sender@test.com"

    def test_get_random_identity_tag_filtered_name_fallback(self):
        """Line 166: get_random_identity falls back to all names when tag filter returns empty."""
        from mercury.services.identity_service import IdentityService

        mock_email = MagicMock()
        mock_email.email = "sender@test.com"
        mock_email.tags = ["matching_tag"]
        mock_email.use_count = 0
        mock_email.last_used_at = None

        mock_name = MagicMock()
        mock_name.name = "Fallback Name"
        mock_name.tags = []
        mock_name.use_count = 0
        mock_name.last_used_at = None

        mock_session = MagicMock()
        mock_session.scalars.side_effect = [
            MagicMock(all=MagicMock(return_value=[mock_email])),
            MagicMock(all=MagicMock(return_value=[mock_name])),
        ]
        mock_session.commit = MagicMock()

        with patch('mercury.services.identity_service.get_session_direct', return_value=mock_session):
            email, name = IdentityService.get_random_identity(tag="nonexistent_tag")

        assert name == "Fallback Name"


# ---------------------------------------------------------------------------
# tracking_service - lines 100, 217
# ---------------------------------------------------------------------------

class TestTrackingServiceCoverage:
    """Cover missing lines in tracking_service.py."""

    def test_get_email_by_id_found(self):
        """Line 100: get_email_by_id returns recipient when found in registry."""
        from mercury.services.tracking_service import TrackingService
        svc = TrackingService(base_url="http://localhost")

        email_id = svc.generate_email_id("test@example.com", campaign_id="c1")
        result = svc.get_email_by_id(email_id)
        assert result == "test@example.com"

    def test_get_email_by_id_not_found(self):
        """Line 100: get_email_by_id returns None when not found."""
        from mercury.services.tracking_service import TrackingService
        svc = TrackingService(base_url="http://localhost")

        result = svc.get_email_by_id("em_nonexistent_id")
        assert result is None

    def test_inject_tracking_no_body_tag(self):
        """Line 217: inject_tracking adds pixel when no </body> tag."""
        from mercury.services.tracking_service import TrackingService
        svc = TrackingService(base_url="http://localhost")
        email_id = "test_email_id"

        html = "<p>Hello</p>"
        result = svc.inject_tracking(html, email_id, "user@test.com",
                                      track_opens=True, track_clicks=False, add_unsubscribe=False)
        assert 'track/open' in result


# ---------------------------------------------------------------------------
# webhook_service - lines 123-124, 205, 282, 325, 341, 387
# ---------------------------------------------------------------------------

class TestWebhookServiceCoverage:
    """Cover missing lines in webhook_service.py."""

    def test_load_webhooks_from_env(self):
        """Lines 123-124: _load_webhooks_from_env handles invalid event names."""
        env = {
            'WEBHOOK_1_URL': 'http://test.example.com/hook',
            'WEBHOOK_1_EVENTS': 'email.sent,invalid.event.name',
        }
        with patch.dict(os.environ, env, clear=False):
            from mercury.services.webhook_service import WebhookService
            svc = WebhookService()
            # Should load without error, invalid events just get a warning
            hooks = svc.get_webhooks()
            env_hooks = [h for h in hooks if h.id == 'env_1']
            assert len(env_hooks) == 1

    @pytest.mark.asyncio
    async def test_get_client_creates_and_reuses(self):
        """Line 205: _get_client creates new client and reuses existing."""
        from mercury.services.webhook_service import WebhookService
        with patch.dict(os.environ, {}, clear=False):
            svc = WebhookService()
        svc._webhooks = {}  # no webhooks from env

        client1 = await svc._get_client()
        client2 = await svc._get_client()
        assert client1 is client2

        await svc.close()

    def test_unregister_webhook_not_found(self):
        """Line 282: unregister_webhook returns False when not found."""
        from mercury.services.webhook_service import WebhookService
        svc = WebhookService()
        svc._webhooks = {}
        result = svc.unregister_webhook("nonexistent-id")
        assert result is False

    @pytest.mark.asyncio
    async def test_notify_no_webhooks(self):
        """Line 325: notify returns empty list when no matching webhooks."""
        from mercury.services.webhook_service import WebhookService, WebhookEvent
        svc = WebhookService()
        svc._webhooks = {}

        results = await svc.notify(WebhookEvent.EMAIL_SENT, {"recipient": "test@example.com"})
        assert results == []

    @pytest.mark.asyncio
    async def test_notify_handles_delivery_exception(self):
        """Line 341: notify filters out exceptions from gather results."""
        from mercury.services.webhook_service import WebhookService, WebhookEvent, WebhookConfig
        svc = WebhookService()
        svc._webhooks = {}

        webhook = WebhookConfig(
            id="test-hook",
            url="http://localhost/hook",
            events=list(WebhookEvent)
        )
        svc._webhooks["test-hook"] = webhook

        # Make _deliver_webhook raise an exception
        async def failing_deliver(*args, **kwargs):
            raise RuntimeError("delivery failed")

        with patch.object(svc, '_deliver_webhook', side_effect=failing_deliver):
            results = await svc.notify(WebhookEvent.EMAIL_SENT, {})
        assert results == []

    @pytest.mark.asyncio
    async def test_notify_email_bounced(self):
        """Line 387: notify_email_bounced calls notify correctly."""
        from mercury.services.webhook_service import WebhookService, WebhookEvent
        svc = WebhookService()
        svc._webhooks = {}

        with patch.object(svc, 'notify', new_callable=AsyncMock) as mock_notify:
            mock_notify.return_value = []
            result = await svc.notify_email_bounced(
                recipient="user@test.com",
                bounce_type="hard",
                category="invalid_address",
                reason="User unknown"
            )
            mock_notify.assert_awaited_once_with(
                WebhookEvent.EMAIL_BOUNCED,
                {
                    'recipient': 'user@test.com',
                    'bounce_type': 'hard',
                    'category': 'invalid_address',
                    'reason': 'User unknown'
                }
            )


# ---------------------------------------------------------------------------
# scheduler_service - lines 102-114, 118-119, 310-311, 324-327, 332-334, 354, 363, 383
# ---------------------------------------------------------------------------

class TestSchedulerServiceCoverage:
    """Cover missing lines in scheduler_service.py."""

    def _make_service(self, use_async=False):
        from mercury.services.scheduler_service import SchedulerService
        svc = SchedulerService(use_async=use_async)
        return svc

    def test_on_job_executed_updates_job(self):
        """Lines 102-114: _on_job_executed updates job metadata."""
        svc = self._make_service(use_async=False)
        from mercury.services.scheduler_service import ScheduledJob, ScheduleType

        job = ScheduledJob(
            id="j1",
            name="TestJob",
            schedule_type=ScheduleType.ONCE,
            scheduled_at=datetime.now(UTC)
        )
        svc._jobs["j1"] = job

        mock_event = MagicMock()
        mock_event.job_id = "j1"

        mock_scheduler_job = MagicMock()
        mock_scheduler_job.next_run_time = datetime.now(UTC) + timedelta(hours=1)

        with patch.object(svc._scheduler, 'get_job', return_value=mock_scheduler_job):
            svc._on_job_executed(mock_event)

        assert job.run_count == 1
        assert job.last_run is not None
        assert job.next_run is not None

    def test_on_job_executed_unknown_job(self):
        """Lines 102-114: _on_job_executed silently handles unknown job id."""
        svc = self._make_service(use_async=False)

        mock_event = MagicMock()
        mock_event.job_id = "nonexistent"
        # Should not raise
        svc._on_job_executed(mock_event)

    def test_on_job_error(self):
        """Lines 118-119: _on_job_error logs error."""
        svc = self._make_service(use_async=False)

        mock_event = MagicMock()
        mock_event.job_id = "j2"
        mock_event.exception = RuntimeError("something failed")
        # Should not raise
        svc._on_job_error(mock_event)

    def test_execute_job_no_callback(self):
        """Lines 310-311: _execute_job with no callback logs error and returns."""
        svc = self._make_service(use_async=False)
        # No callback registered - should log and return cleanly
        svc._execute_job("unknown_job_id")

    def test_execute_job_sync_callback(self):
        """Lines 324-327: _execute_job runs sync callback."""
        svc = self._make_service(use_async=False)
        from mercury.services.scheduler_service import ScheduledJob, ScheduleType

        called_with = {}

        def sync_callback(**kwargs):
            called_with.update(kwargs)

        job = ScheduledJob(
            id="sync_job",
            name="SyncJob",
            schedule_type=ScheduleType.ONCE,
            scheduled_at=datetime.now(UTC),
            metadata={"key": "value"}
        )
        svc._jobs["sync_job"] = job
        svc._callbacks["sync_job"] = sync_callback

        svc._execute_job("sync_job")
        assert called_with == {"key": "value"}

    def test_execute_job_async_callback_background_scheduler(self):
        """Lines 332-334: _execute_job runs async callback via new event loop in non-async mode."""
        svc = self._make_service(use_async=False)
        from mercury.services.scheduler_service import ScheduledJob, ScheduleType

        async def async_callback(**kwargs):
            pass

        job = ScheduledJob(
            id="async_job",
            name="AsyncJob",
            schedule_type=ScheduleType.ONCE,
            scheduled_at=datetime.now(UTC),
            metadata={}
        )
        svc._jobs["async_job"] = job
        svc._callbacks["async_job"] = async_callback

        # Should run without error
        svc._execute_job("async_job")

    def test_pause_job_not_found(self):
        """Line 354: pause_job returns False for unknown job."""
        svc = self._make_service(use_async=False)
        result = svc.pause_job("nonexistent")
        assert result is False

    def test_resume_job_not_found(self):
        """Line 363: resume_job returns False for unknown job."""
        svc = self._make_service(use_async=False)
        result = svc.resume_job("nonexistent")
        assert result is False

    def test_reschedule_job_not_found(self):
        """Line 383: reschedule_job returns False for unknown job."""
        svc = self._make_service(use_async=False)
        result = svc.reschedule_job("nonexistent", datetime.now(UTC))
        assert result is False

    def test_schedule_once_creates_job(self):
        """schedule_once creates a ScheduledJob."""
        svc = self._make_service(use_async=False)
        run_at = datetime.now(UTC) + timedelta(hours=1)
        callback = MagicMock()

        with patch.object(svc._scheduler, 'add_job'):
            job = svc.schedule_once("job1", "Test Job", run_at, callback, campaign_id="camp1")

        assert job.id == "job1"
        assert job.campaign_id == "camp1"

    def test_schedule_recurring_creates_job(self):
        """schedule_recurring creates a ScheduledJob."""
        svc = self._make_service(use_async=False)
        callback = MagicMock()

        mock_scheduler_job = MagicMock()
        mock_scheduler_job.next_run_time = datetime.now(UTC) + timedelta(hours=1)

        with patch.object(svc._scheduler, 'add_job'), \
             patch.object(svc._scheduler, 'get_job', return_value=mock_scheduler_job):
            job = svc.schedule_recurring("job2", "Recurring Job", "0 9 * * 1-5", callback)

        assert job.id == "job2"
        assert job.cron_expression == "0 9 * * 1-5"

    def test_schedule_interval_creates_job(self):
        """schedule_interval creates a ScheduledJob."""
        svc = self._make_service(use_async=False)
        callback = MagicMock()

        mock_scheduler_job = MagicMock()
        mock_scheduler_job.next_run_time = datetime.now(UTC) + timedelta(seconds=60)

        with patch.object(svc._scheduler, 'add_job'), \
             patch.object(svc._scheduler, 'get_job', return_value=mock_scheduler_job):
            job = svc.schedule_interval("job3", "Interval Job", 60, callback)

        assert job.id == "job3"
        assert job.interval_seconds == 60

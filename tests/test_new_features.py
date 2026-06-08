"""Tests for newly added features."""

import pytest
from datetime import datetime, UTC


class TestEncryption:
    """Test encryption service."""

    def test_encrypt_decrypt(self):
        """Test basic encryption and decryption."""
        from mercury.security.encryption import EncryptionService

        service = EncryptionService(password="test-password")

        plaintext = "my_secret_password"
        encrypted = service.encrypt(plaintext)
        decrypted = service.decrypt(encrypted)

        assert decrypted == plaintext
        assert encrypted != plaintext

    def test_is_encrypted(self):
        """Test encrypted value detection."""
        from mercury.security.encryption import EncryptionService

        service = EncryptionService(password="test-password")

        # Encrypt a longer string to ensure it's detected as encrypted
        encrypted = service.encrypt("test_password_that_is_long_enough")

        assert service.is_encrypted(encrypted)
        assert not service.is_encrypted("plain_text")
        assert not service.is_encrypted("")

    def test_encrypt_if_needed(self):
        """Test conditional encryption."""
        from mercury.security.encryption import EncryptionService

        service = EncryptionService(password="test-password")

        # Encrypt a longer string
        encrypted = service.encrypt("test_password_that_is_long_enough")

        # Already encrypted - should not re-encrypt
        result = service.encrypt_if_needed(encrypted)
        assert result == encrypted

        # Not encrypted - should encrypt
        result = service.encrypt_if_needed("plain")
        # Just verify it can decrypt correctly
        decrypted = service.decrypt(result)
        assert decrypted == "plain"


class TestEmailValidation:
    """Test email validation utilities."""

    def test_valid_email(self):
        """Test valid email addresses."""
        from mercury.utils.validation import validate_email, is_valid_email

        result = validate_email("test@example.com")
        assert result.is_valid
        assert result.normalized_email == "test@example.com"
        assert result.domain == "example.com"

        assert is_valid_email("test@example.com")

    def test_invalid_email(self):
        """Test invalid email addresses."""
        from mercury.utils.validation import validate_email, is_valid_email

        result = validate_email("not-an-email")
        assert not result.is_valid
        assert result.error is not None

        assert not is_valid_email("not-an-email")
        assert not is_valid_email("")

    def test_batch_validation(self):
        """Test batch email validation."""
        from mercury.utils.validation import validate_emails_batch

        emails = [
            "valid1@example.com",
            "valid2@example.com",
            "invalid-email",
            "valid1@example.com",  # Duplicate
            "",
        ]

        valid, invalid = validate_emails_batch(emails, deduplicate=True)

        assert len(valid) == 2
        assert len(invalid) == 1


class TestTrackingService:
    """Test tracking service."""

    def test_generate_tracking_pixel(self):
        """Test tracking pixel generation."""
        from mercury.services.tracking_service import TrackingService

        service = TrackingService(base_url="https://example.com")
        email_id = service.generate_email_id("test@example.com")

        pixel = service.generate_tracking_pixel(email_id)

        assert "<img" in pixel
        assert email_id in pixel
        assert 'width="1"' in pixel

    def test_wrap_link(self):
        """Test link wrapping for click tracking."""
        from mercury.services.tracking_service import TrackingService

        service = TrackingService(base_url="https://example.com")

        wrapped = service.wrap_link("https://original.com/page", "email123")

        assert "example.com/track/click/email123" in wrapped
        assert "original.com" in wrapped

    def test_inject_tracking(self):
        """Test tracking injection into HTML."""
        from mercury.services.tracking_service import TrackingService

        service = TrackingService(base_url="https://example.com")

        html = '<html><body><a href="https://link.com">Click</a></body></html>'

        result = service.inject_tracking(html, email_id="test123", recipient="test@example.com")

        # Should have tracking pixel
        assert "<img" in result
        # Should have wrapped link
        assert "/track/click/" in result


class TestBounceService:
    """Test bounce handling service."""

    def test_categorize_hard_bounce(self):
        """Test hard bounce categorization."""
        from mercury.services.bounce_service import BounceService, BounceType, BounceCategory

        service = BounceService()

        bounce_type, category = service.categorize_bounce(
            "550", "User unknown in virtual mailbox table"
        )

        assert bounce_type == BounceType.HARD
        assert category == BounceCategory.INVALID_ADDRESS

    def test_categorize_soft_bounce(self):
        """Test soft bounce categorization."""
        from mercury.services.bounce_service import BounceService, BounceType, BounceCategory

        service = BounceService()

        bounce_type, category = service.categorize_bounce("452", "Mailbox full")

        assert bounce_type == BounceType.SOFT
        assert category == BounceCategory.MAILBOX_FULL


class TestWebhookService:
    """Test webhook service."""

    def test_register_webhook(self):
        """Test webhook registration."""
        from mercury.services.webhook_service import WebhookService, WebhookEvent

        service = WebhookService()

        webhook = service.register_webhook(
            url="https://example.com/webhook",
            events=[WebhookEvent.EMAIL_SENT],
            secret="test-secret",
        )

        assert webhook.url == "https://example.com/webhook"
        assert WebhookEvent.EMAIL_SENT in webhook.events
        assert webhook.secret == "test-secret"

    def test_signature_generation(self):
        """Test HMAC signature generation."""
        from mercury.services.webhook_service import WebhookService

        service = WebhookService()

        signature = service._generate_signature('{"event": "test"}', "secret123")

        assert signature.startswith("sha256=")
        assert len(signature) > 10


class TestSchedulerService:
    """Test scheduler service."""

    def test_schedule_once(self):
        """Test one-time scheduling."""
        from mercury.services.scheduler_service import SchedulerService, ScheduleType
        from datetime import timedelta

        service = SchedulerService(use_async=False)
        service.start()

        try:
            run_time = datetime.now(UTC) + timedelta(hours=1)

            job = service.schedule_once(
                job_id="test_job", name="Test Job", run_at=run_time, callback=lambda: None
            )

            assert job.id == "test_job"
            assert job.schedule_type == ScheduleType.ONCE
            assert job.next_run is not None

            # Cancel the job
            assert service.cancel_job("test_job")
            assert service.get_job("test_job") is None

        finally:
            service.stop()

    def test_job_management(self):
        """Test job pause/resume."""
        from mercury.services.scheduler_service import SchedulerService
        from datetime import timedelta

        service = SchedulerService(use_async=False)
        service.start()

        try:
            run_time = datetime.now(UTC) + timedelta(hours=1)

            service.schedule_once(
                job_id="managed_job", name="Managed Job", run_at=run_time, callback=lambda: None
            )

            # Pause
            assert service.pause_job("managed_job")
            assert not service.get_job("managed_job").enabled

            # Resume
            assert service.resume_job("managed_job")
            assert service.get_job("managed_job").enabled

        finally:
            service.stop()


class TestAsyncFileIO:
    """Test async file I/O utilities."""

    @pytest.mark.asyncio
    async def test_async_write_read(self, tmp_path):
        """Test async file write and read."""
        from mercury.utils.async_io import async_write_file, async_read_file

        test_file = tmp_path / "test.txt"
        content = "Hello, async world!"

        await async_write_file(str(test_file), content)
        result = await async_read_file(str(test_file))

        assert result == content

    @pytest.mark.asyncio
    async def test_async_file_logger(self, tmp_path):
        """Test async file logger."""
        from mercury.utils.async_io import AsyncFileLogger

        log_file = tmp_path / "test.log"

        async with AsyncFileLogger(str(log_file), buffer_size=2) as logger:
            await logger.log("Line 1")
            await logger.log("Line 2")
            await logger.log("Line 3")

        # File should exist with content
        assert log_file.exists()
        content = log_file.read_text()
        assert "Line 1" in content
        assert "Line 2" in content
        assert "Line 3" in content


class TestStructuredLogging:
    """Test structured logging configuration."""

    def test_configure_logging(self):
        """Test logging configuration."""
        from mercury.utils.logging_config import configure_logging, get_logger

        configure_logging(level="DEBUG", json_output=False)

        logger = get_logger("test")
        assert logger is not None

    def test_email_send_logger(self):
        """Test specialized email logger."""
        from mercury.utils.logging_config import EmailSendLogger

        logger = EmailSendLogger(campaign_id="test_campaign")

        # Should not raise
        logger.log_send_start("test@example.com", "corr123", "smtp1")
        logger.log_send_success("test@example.com", "corr123", "smtp1", 150.5)

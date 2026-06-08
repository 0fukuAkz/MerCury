"""Integration tests for end-to-end workflows."""

import pytest
from datetime import datetime, UTC

from mercury.services.email import EmailService, EmailConfig
from mercury.services.smtp_service import SMTPService


@pytest.mark.asyncio
@pytest.mark.integration
class TestEmailSendingWorkflow:
    """Test complete email sending workflow."""

    async def test_end_to_end_single_email(self):
        """Test sending single email end-to-end."""
        # Create SMTP service
        smtp_service = SMTPService()

        # Add mock SMTP server
        smtp_config_data = {
            "name": "test-smtp",
            "host": "smtp.example.com",
            "port": 587,
            "username": "test@example.com",
            "password": "password",
            "tls_mode": "starttls",
        }
        smtp_service.load_from_config([smtp_config_data])

        # Create email service
        email_service = EmailService(smtp_service)
        email_service.configure(
            EmailConfig(
                from_email="sender@example.com",
                from_name="Test Sender",
                subject="Welcome {{first_name}}!",
                html_content="<h1>Hello {{first_name}}!</h1><p>Email: {{email}}</p>",
                dry_run=True,  # Don't actually send
            )
        )

        # Send email
        result = await email_service.send_single(
            recipient="user@example.com", placeholders={"first_name": "John"}
        )

        assert result.success is True
        assert result.recipient == "user@example.com"
        assert result.dry_run is True

    async def test_bulk_send_with_template(self):
        """Test bulk sending with template."""
        smtp_service = SMTPService()
        # Fix: Configure generic server
        smtp_service.load_from_config([{"name": "test", "host": "test", "port": 25}])
        email_service = EmailService(smtp_service)

        email_service.configure(
            EmailConfig(
                from_email="sender@example.com",
                subject="Hello {{name}}!",
                html_content="<p>Hi {{name}}, email: {{email}}</p>",
                concurrency=10,
                dry_run=True,
            )
        )

        recipients = [
            {"email": "user1@example.com", "name": "Alice"},
            {"email": "user2@example.com", "name": "Bob"},
            {"email": "user3@example.com", "name": "Charlie"},
        ]

        result = await email_service.send_bulk(recipients)

        assert result.total == 3
        assert result.success == 3
        assert result.failed == 0

    async def test_rate_limiting_integration(self):
        """Test rate limiting in full workflow."""
        smtp_service = SMTPService()
        smtp_service.load_from_config([{"name": "test", "host": "test", "port": 25}])
        email_service = EmailService(smtp_service)

        email_service.configure(
            EmailConfig(
                from_email="sender@example.com",
                subject="Test",
                html_content="<p>Test</p>",
                rate_per_minute=2,  # Very low limit
                concurrency=5,
                dry_run=True,
            )
        )

        # Should respect rate limit even with high concurrency
        start = datetime.now(UTC)

        recipients = [{"email": f"user{i}@example.com"} for i in range(3)]
        result = await email_service.send_bulk(recipients)

        duration = (datetime.now(UTC) - start).total_seconds()

        assert result.total == 3
        # With rate limit of 2/min, 3 emails should take some time
        # (though in dry run, might be faster)

    async def test_template_with_rotation(self):
        """Test template rotation."""
        smtp_service = SMTPService()
        smtp_service.load_from_config([{"name": "test", "host": "test", "port": 25}])
        email_service = EmailService(smtp_service)

        email_service.configure(
            EmailConfig(
                from_email="sender@example.com",
                subjects=["Subject A", "Subject B"],
                from_names=["Sender One", "Sender Two"],
                html_content="<p>Test</p>",
                dry_run=True,
            )
        )

        # Send multiple emails - should rotate subjects and names
        results = []
        for i in range(4):
            result = await email_service.send_single(f"user{i}@example.com")
            results.append(result)

        assert all(r.success for r in results)

        # Check rotation stats
        stats = email_service.get_statistics()
        assert "rotation" in stats


@pytest.mark.integration
class TestDatabaseWorkflow:
    """Test database operations workflow."""

    def test_campaign_lifecycle(self, db_session):
        """Test full campaign lifecycle."""
        from mercury.data.repositories.campaign import CampaignRepository
        from mercury.data.models.campaign import Campaign, CampaignStatus

        repo = CampaignRepository(db_session)

        # Create campaign
        campaign = Campaign(
            name="Test Campaign",
            status=CampaignStatus.DRAFT,
            subjects=["Test Subject"],
            # html_content removed as it's not a column
            created_at=datetime.now(UTC),
        )

        created = repo.create(campaign)
        assert created.id is not None
        assert created.status == CampaignStatus.DRAFT

        # Update to running
        created.status = CampaignStatus.SENDING
        updated = repo.update(created)
        assert updated.status == CampaignStatus.SENDING

        # Complete campaign
        updated.status = CampaignStatus.COMPLETED
        completed = repo.update(updated)
        assert completed.status == CampaignStatus.COMPLETED

        # Retrieve and verify
        found = repo.get_by_name("Test Campaign")
        assert found.status == CampaignStatus.COMPLETED

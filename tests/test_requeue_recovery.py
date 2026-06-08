from unittest.mock import AsyncMock, MagicMock, patch
from mercury.data.models.campaign import Campaign, CampaignStatus
from mercury.data.models.dead_letter import DeadLetter
from mercury.data.repositories.campaign import CampaignRepository
from mercury.data.repositories.dead_letter import DeadLetterRepository
from mercury.services.campaign_service import CampaignService


def test_campaign_filtering_emails(db_session):
    """Verify that run_campaign surgically filters recipients based on filter_emails in settings."""
    service = CampaignService()
    service.email_service = MagicMock()
    service.email_service.send_bulk = AsyncMock()
    service.email_service.get_statistics.return_value = {}

    # Mock current campaign with filter_emails configuration
    campaign = Campaign(
        id=123,
        name="Test",
        status=CampaignStatus.DRAFT,
        settings={"filter_emails": ["failed1@example.com", "failed2@example.com"]},
    )
    service._current_campaign = campaign

    # Large recipients list
    recipients = [
        {"email": "success@example.com", "name": "Success"},
        {"email": "failed1@example.com", "name": "Failed 1"},
        {"email": "failed2@example.com", "name": "Failed 2"},
    ]

    # Running campaign should surgically filter recipients
    with patch("mercury.services.campaign_service.get_session_direct"), patch(
        "mercury.services.campaign_service.AsyncFileLogger"
    ) as mock_logger:
        # We mock send_bulk return value
        mock_bulk_result = MagicMock()
        mock_bulk_result.results = []
        service.email_service.send_bulk.return_value = mock_bulk_result

        # Run campaign
        import asyncio

        asyncio.run(service.run_campaign(recipients, log_path="logs"))

        # The email service send_bulk should have been called only with filtered recipients
        args, kwargs = service.email_service.send_bulk.call_args
        sent_recipients = kwargs.get("recipients") or args[0]
        assert len(sent_recipients) == 2
        assert sent_recipients[0]["email"] == "failed1@example.com"
        assert sent_recipients[1]["email"] == "failed2@example.com"


def test_api_requeue_all_dead_letters(client, db_session, auth_headers):
    """Test the api_requeue_all_dead_letters route correctly clones the campaign and sets filter_emails."""
    # 1. Create a source campaign
    camp_repo = CampaignRepository(db_session)
    src_campaign = Campaign(
        name="Original Campaign",
        description="Original description",
        status=CampaignStatus.COMPLETED,
        template_id=None,
        from_email="sender@example.com",
        from_name="Sender",
        reply_to="reply@example.com",
        subjects=["Subject 1", "Subject 2"],
        concurrency=10,
        chunk_size=100,
        settings={"recipients_path": "path/to/original.csv", "dry_run": False},
    )
    src_campaign = camp_repo.create(src_campaign)

    # 2. Add some dead letters referencing the source campaign
    dl_repo = DeadLetterRepository(db_session)
    dl1 = DeadLetter(
        recipient="failed1@example.com",
        subject="Subject 1",
        html_body="<p>Body</p>",
        from_email="sender@example.com",
        error_type="mailbox_error",
        error_message="Host unknown",
        campaign_id=src_campaign.id,
    )
    dl2 = DeadLetter(
        recipient="failed2@example.com",
        subject="Subject 1",
        html_body="<p>Body</p>",
        from_email="sender@example.com",
        error_type="rate_limit",
        error_message="Too many requests",
        campaign_id=src_campaign.id,
    )
    dl_repo.create(dl1)
    dl_repo.create(dl2)

    # 3. Post to the requeue-all endpoint
    resp = client.post("/api/dead-letter/requeue-all", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json
    assert data["success"] is True
    assert "campaigns" in data["redirect_url"]

    # 4. Verify in the database that a new campaign has been created
    # and unresolved dead letters are marked as resolved
    db_session.expire_all()

    dl_items = dl_repo.get_unresolved()
    assert len(dl_items) == 0  # Marked resolved!

    # Get all campaigns and find the clone
    campaigns = camp_repo.get_recent(5)
    clone = next(c for c in campaigns if c.id != src_campaign.id)

    assert clone.name == "Original Campaign (Dead Letter Recovery)"
    assert clone.from_email == "sender@example.com"
    assert clone.concurrency == 10
    assert clone.chunk_size == 100
    assert clone.status == CampaignStatus.DRAFT

    # Verify filter_emails is stored, and recipients_path is preserved
    assert set(clone.settings["filter_emails"]) == {"failed1@example.com", "failed2@example.com"}
    assert clone.settings["recipients_path"] == "path/to/original.csv"

"""Tests for campaign_service.py coverage."""

import pytest
import asyncio
from unittest.mock import patch, MagicMock
from mercury.services.campaign_service import (
    CampaignService,
    CampaignConfig,
    load_campaign_from_yaml,
)


@pytest.fixture(autouse=True)
def patch_session(db_engine):
    from sqlalchemy.orm import sessionmaker

    TestSession = sessionmaker(bind=db_engine)
    with patch(
        "mercury.services.campaign_service.get_session_direct", side_effect=TestSession
    ), patch("mercury.data.database.get_session_direct", side_effect=TestSession):
        yield


@pytest.fixture
def mock_campaign_config():
    return CampaignConfig(
        name="Test",
        from_emails=["test@example.com"],
        subject="Test",
        recipients_path="/tmp/does-not-exist.csv",
    )


def test_campaign_load_config_defaults(db_session):
    from mercury.services.identity_service import IdentityService
    IdentityService.add_email("test@example.com")
    IdentityService.add_name("Test Name")

    service = CampaignService()
    service.initialize()
    config = CampaignConfig(name="Test")
    # Will fallback to defaults
    service.load_config(config)

    assert config.from_emails is not None
    assert config.from_email == "test@example.com"
    assert config.from_name == "Test Name"


def test_campaign_pause_resume():
    service = CampaignService()
    service.pause()
    assert service._paused is True
    service.resume()
    assert service._paused is False
    service.stop()
    assert service._running is False
    assert service._shutdown_event.is_set()


@pytest.mark.asyncio
async def test_campaign_run_campaign_empty(db_session, mock_campaign_config):
    service = CampaignService()
    service.initialize()
    service.load_config(mock_campaign_config)

    service._current_campaign = service.create_campaign(mock_campaign_config)

    # Run with empty recipients
    stats = await service.run_campaign([])
    assert stats["total"] == 0
    assert stats["sent"] == 0
    await service.close()


def test_campaign_load_csv_invalid_file():
    service = CampaignService()
    with pytest.raises(FileNotFoundError):
        list(service.load_recipients_from_csv("/nonexistent/file.csv"))


def test_campaign_load_txt_invalid_file():
    service = CampaignService()
    with pytest.raises(FileNotFoundError):
        list(service.load_recipients_from_text("/nonexistent/file.txt"))


def test_campaign_stats_empty():
    service = CampaignService()
    assert service.get_campaign_stats() == {}


@pytest.mark.asyncio
async def test_campaign_run_with_results(db_session, mock_campaign_config):
    service = CampaignService()
    service.initialize()
    service.load_config(mock_campaign_config)
    service._current_campaign = service.create_campaign(mock_campaign_config)

    recipients = [{"email": "user1@test.com"}, {"email": "user2@test.com"}]

    # Mock email_service send_bulk to return 1 success, 1 failure
    mock_result = MagicMock()
    res1 = MagicMock()
    res1.success = True
    res1.recipient = "user1@test.com"
    res1.smtp_server = "Server 1"
    res1.correlation_id = "test-corr-1"

    res2 = MagicMock()
    res2.success = False
    res2.recipient = "user2@test.com"
    res2.error = "Timeout"
    res2.error_type = "network"
    res2.correlation_id = "test-corr-2"

    mock_result.results = [res1, res2]

    service.email_service.send_bulk = MagicMock(return_value=asyncio.Future())
    service.email_service.send_bulk.return_value.set_result(mock_result)

    stats = await service.run_campaign(recipients)

    assert stats["total"] == 2
    assert stats["sent"] == 1
    assert stats["failed"] == 1

    # Check DB logs
    from mercury.data.models import EmailLog

    # Use a fresh session to ensure we see committed data if needed,
    # but db_session fixture should see it if committed.
    logs = db_session.query(EmailLog).all()
    assert len(logs) == 2

    await service.close()


def test_load_yaml_missing(tmp_path):
    import yaml

    yaml_file = tmp_path / "test.yaml"
    with open(yaml_file, "w") as f:
        yaml.dump(
            {
                "campaign": {"name": "YAML"},
                "email": {"subject": "Hi"},
                "smtp_providers": [{"host": "smtp"}],
            },
            f,
        )

    config = load_campaign_from_yaml(str(yaml_file))
    assert config.name == "YAML"
    assert config.subject == "Hi"

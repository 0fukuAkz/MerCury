"""
Tests for error handling edge cases in CampaignService.
"""
import pytest
import asyncio
from unittest.mock import MagicMock, patch, mock_open
from sqlalchemy.exc import SQLAlchemyError

from mercury.services.campaign_service import CampaignService, CampaignConfig
from mercury.data.models import Campaign

@pytest.fixture
def service():
    svc = CampaignService()
    svc.email_service = MagicMock()
    return svc

@pytest.fixture
def valid_config():
    return CampaignConfig(
        name="Test Campaign",
        subject="Subject",
        from_email="test@example.com",
        recipients_path="test.csv"
    )

class TestCampaignServiceErrors:

    def test_load_recipients_file_not_found(self, service):
        """Verify FileNotFoundError is raised for non-existent CSV."""
        with pytest.raises(FileNotFoundError):
            list(service.load_recipients_from_csv("non_existent.csv"))

    def test_load_recipients_missing_column_graceful(self, service):
        """Verify behavior when email column is missing."""
        # Setup malformed CSV data (valid CSV format, but missing email column)
        csv_content = "name,phone\nJohn,123456\nJane,789101"
        
        with patch("os.path.exists", return_value=True), \
             patch("builtins.open", mock_open(read_data=csv_content)), \
             patch("mercury.services.campaign_service.logger") as mock_logger:
            
            recipients = list(service.load_recipients_from_csv("test.csv", email_column="email"))
            
            # Should be empty because no email column found/matched
            assert len(recipients) == 0
            # Should warn
            mock_logger.warning.assert_called()
            args, _ = mock_logger.warning.call_args
            assert "Email column 'email' not found" in args[0]

    def test_create_campaign_db_error(self, service, valid_config):
        """Verify database errors during campaign creation propagate."""
        with patch('mercury.services.campaign_service.get_session_direct') as mock_session_cls:
            mock_session = mock_session_cls.return_value
            # Setup repository to raise exception
            with patch('mercury.services.campaign_service.CampaignRepository') as MockRepo:
                MockRepo.return_value.create.side_effect = SQLAlchemyError("DB Connection Failed")
                
                with pytest.raises(SQLAlchemyError):
                    service.create_campaign(valid_config)
            
            # Verify session closed even after error
            mock_session.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_campaign_no_service(self, service):
        """Verify RuntimeError if email service not configured."""
        service.email_service = None
        with pytest.raises(RuntimeError, match="Email service not configured"):
            await service.run_campaign([])

    @pytest.mark.asyncio
    async def test_run_campaign_db_commit_error(self, service):
        """Verify campaign stops if DB persistence fails during batch.

        run_campaign now batches log writes through LogRepository.bulk_create,
        so the failure surface lives there, not on raw session.commit.
        """
        # Setup
        service._current_campaign = Campaign(id=1, name="Test")
        recipients = [{"email": "test@example.com"}]

        # Mock dependencies
        mock_result = MagicMock()
        mock_result.results = [MagicMock(success=True, recipient="test@example.com", server_name="smtp1")]
        service.email_service.send_bulk = MagicMock(return_value=mod_result_future(mock_result))

        with patch('mercury.services.campaign_service.get_session_direct') as mock_session_cls, \
             patch('mercury.services.campaign_service.LogRepository') as MockLogRepo, \
             patch('mercury.services.campaign_service.AsyncFileLogger') as MockLogger:

            mock_session = mock_session_cls.return_value
            # Simulate persistence failure inside bulk_create — the new code path.
            MockLogRepo.return_value.bulk_create.side_effect = SQLAlchemyError("Commit Failed")

            # Setup logger context managers
            mock_logger_instance = MagicMock()
            mock_logger_instance.log_success = MagicMock(return_value=mod_result_future(None))
            mock_logger_instance.log_failure = MagicMock(return_value=mod_result_future(None))

            MockLogger.return_value.__aenter__.return_value = mock_logger_instance

            with pytest.raises(SQLAlchemyError, match="Commit Failed"):
                await service.run_campaign(recipients)

            # Verify clean up (session closed) and running flag cleared.
            mock_session.close.assert_called()
            assert service._running is False

def mod_result_future(result):
    f = asyncio.Future()
    f.set_result(result)
    return f

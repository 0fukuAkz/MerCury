"""Tests for Service Layer (CampaignService, SMTPService)."""

import pytest
import os
from unittest.mock import patch, Mock, MagicMock, mock_open, AsyncMock
from mercury.services.campaign_service import CampaignService, CampaignConfig
from mercury.services.smtp_service import SMTPService
from mercury.data.models import Campaign, SMTPServer

@pytest.fixture
def mock_db_session():
    with patch('mercury.services.campaign_service.get_session_direct') as mock_get, \
         patch('mercury.services.smtp_service.get_session_direct') as mock_get_smtp:
        session = Mock()
        mock_get.return_value = session
        mock_get_smtp.return_value = session
        yield session

@pytest.fixture
def mock_repo():
    with patch('mercury.services.campaign_service.CampaignRepository') as MockRepo:
        yield MockRepo

@pytest.fixture
def mock_smtp_repo():
    with patch('mercury.services.smtp_service.SMTPRepository') as MockRepo:
        yield MockRepo

# --- CampaignService Tests ---

def test_campaign_service_initialization():
    with patch('mercury.services.campaign_service.init_db') as mock_init:
        service = CampaignService()
        service.initialize()
        mock_init.assert_called_once()
        assert service.bounce_service is not None

def test_campaign_service_load_config():
    service = CampaignService()
    config = CampaignConfig(name="Test", subject="Sub", from_email="f@e.com")
    
    with patch.object(service.smtp_service, 'load_from_database') as mock_load_smtp:
        service.load_config(config)
        assert service.config == config
        assert service.email_service is not None
        mock_load_smtp.assert_called_once()

def test_campaign_service_create_campaign(mock_db_session, mock_repo):
    service = CampaignService()
    config = CampaignConfig(name="New Campaign", subject="Hi")
    
    # Correctly configure mock name
    mock_created = Mock(id=1)
    mock_created.name = "New Campaign"
    mock_repo.return_value.create.return_value = mock_created
    
    campaign = service.create_campaign(config)
    
    assert campaign.id == 1
    assert campaign.name == "New Campaign"
    mock_repo.return_value.create.assert_called_once()

def test_campaign_service_create_campaign_with_rotation(mock_db_session, mock_repo):
    service = CampaignService()
    config = CampaignConfig(
        name="Rotation Campaign",
        subject="Hi",
        smtp_rotation="random"
    )
    
    mock_repo.return_value.create.side_effect = lambda c: c # Return argument passed
    
    campaign = service.create_campaign(config)
    
    assert campaign.smtp_rotation_strategy == "random"

# ...

def test_smtp_service_get_pool():
    service = SMTPService()
    service.load_from_config([{'name': 's1', 'host': 'h1'}])
    
    pool = service.get_connection_pool()
    assert pool.configs[0].name == 's1'
    
    # Should return same instance
    assert service.get_connection_pool() is pool

def test_load_recipients_from_csv_simple():
    service = CampaignService()
    csv_content = "email,name\na@b.com,Alice\nc@d.com,Bob"
    
    with patch('os.path.exists', return_value=True), \
         patch('builtins.open', mock_open(read_data=csv_content)):
        
        recipients = list(service.load_recipients_from_csv("dummy.csv"))
        assert len(recipients) == 2
        assert recipients[0]['email'] == 'a@b.com'
        assert recipients[0]['name'] == 'Alice'

def test_load_recipients_from_csv_deduplicate():
    service = CampaignService()
    csv_content = "email\na@b.com\na@b.com"
    
    with patch('os.path.exists', return_value=True), \
         patch('builtins.open', mock_open(read_data=csv_content)):
        
        recipients = list(service.load_recipients_from_csv("dummy.csv", deduplicate=True))
        assert len(recipients) == 1

def test_load_recipients_from_csv_validation():
    service = CampaignService()
    csv_content = "email\ninvalid-email\na@b.com"
    
    with patch('os.path.exists', return_value=True), \
         patch('builtins.open', mock_open(read_data=csv_content)):
        
        recipients = list(service.load_recipients_from_csv("dummy.csv", validate=True))
        assert len(recipients) == 1
        assert recipients[0]['email'] == 'a@b.com'

@pytest.mark.asyncio
async def test_run_campaign_flow():
    service = CampaignService()
    service.email_service = AsyncMock()
    service.config = CampaignConfig(name="Test", chunk_size=2)
    
    # Mock send_bulk result
    bulk_result = Mock()
    bulk_result.results = [
        Mock(success=True, recipient='a@b.com', smtp_server='smtp1', error_type=None),
        Mock(success=False, recipient='c@d.com', error='Fail', smtp_server=None, error_type='auth_error')
    ]
    service.email_service.send_bulk.return_value = bulk_result
    
    recipients = [{'email': 'a@b.com'}, {'email': 'c@d.com'}]
    
    with patch('mercury.services.campaign_service.AsyncFileLogger') as MockLogger:
        # Mock async context manager for logger
        mock_logger_instance = AsyncMock()
        MockLogger.return_value.__aenter__.return_value = mock_logger_instance
        
        stats = await service.run_campaign(recipients, log_path="logs")
        
        assert stats['total'] == 2
        assert stats['sent'] == 1
        assert stats['failed'] == 1
        assert stats['chunks_processed'] == 1
        
        mock_logger_instance.log_success.assert_called_once()
        mock_logger_instance.log_failure.assert_called_once()

# --- SMTPService Tests ---

def test_smtp_service_load_from_database(mock_db_session, mock_smtp_repo):
    service = SMTPService()
    
    mock_server = Mock(spec=SMTPServer)
    mock_server.name = "smtp1"
    mock_server.host = "host1"
    mock_server.port = 587
    # Mock other attributes used in SMTPServerConfig
    mock_server.username = "u"
    mock_server.password = "p"
    mock_server.use_tls = True
    mock_server.use_ssl = False
    mock_server.use_auth = True
    mock_server.timeout = 30
    mock_server.from_email = ""
    mock_server.from_name = ""
    mock_server.weight = 1
    mock_server.priority = 0
    mock_server.max_per_minute = 100
    mock_server.max_per_hour = 1000
    
    mock_smtp_repo.return_value.get_active.return_value = [mock_server]
    
    configs = service.load_from_database()
    assert len(configs) == 1
    assert configs[0].name == "smtp1"

def test_smtp_service_add_server(mock_db_session, mock_smtp_repo):
    service = SMTPService()
    mock_created = Mock(name="new", host="h")
    mock_smtp_repo.return_value.create.return_value = mock_created
    
    server = service.add_server(name="new", host="h")
    assert server == mock_created
    mock_smtp_repo.return_value.create.assert_called_once()

@pytest.mark.asyncio
async def test_smtp_service_test_connection_success():
    service = SMTPService()
    service.load_from_config([{'name': 's1', 'host': 'h1'}])
    
    with patch('mercury.engine.connection_pool.AsyncSMTPConnection') as MockConn:
        mock_conn_instance = AsyncMock()
        MockConn.return_value = mock_conn_instance
        
        result = await service.test_connection('s1')
        
        assert result['success'] is True
        assert result['message'] == 'Connection successful'
        mock_conn_instance.connect.assert_awaited_once()
        mock_conn_instance.close.assert_awaited_once()

@pytest.mark.asyncio
async def test_smtp_service_test_connection_fail():
    service = SMTPService()
    service.load_from_config([{'name': 's1', 'host': 'h1'}])
    
    with patch('mercury.engine.connection_pool.AsyncSMTPConnection') as MockConn:
        mock_conn_instance = AsyncMock()
        MockConn.return_value = mock_conn_instance
        mock_conn_instance.connect.side_effect = Exception("Conn Fail")
        
        result = await service.test_connection('s1')
        
        assert result['success'] is False
        assert result['error'] == 'Conn Fail'



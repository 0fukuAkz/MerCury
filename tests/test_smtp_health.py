"""Tests for SMTP health checking and self-healing endpoints/service."""

import os
import datetime
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from sqlalchemy.orm import sessionmaker

from mercury.data.models.smtp import SMTPServer, SMTPServerStatus
from mercury.services.smtp_service import SMTPService

@pytest.fixture
def app_no_login(db_engine):
    """App fixture with LOGIN_DISABLED=True."""
    from mercury.web.app import create_app
    from mercury.app_context import AppContext

    mock_context = MagicMock(spec=AppContext)
    mock_context.limiter = MagicMock()
    mock_context.limiter.limit = lambda x: lambda f: f
    mock_context.socketio = MagicMock()
    mock_context.is_initialized = False

    TestSession = sessionmaker(bind=db_engine)

    with patch('mercury.web.app.init_db'), \
         patch('mercury.security.auth.UserRepository') as MockRepo, \
         patch('mercury.web.app.get_app_context', return_value=mock_context), \
         patch('mercury.data.database.get_session_direct', side_effect=TestSession), \
         patch('mercury.services.smtp_service.get_session_direct', side_effect=TestSession), \
         patch('mercury.services.campaign_service.get_session_direct', side_effect=TestSession), \
         patch('mercury.web.routes.api.get_session_direct', side_effect=TestSession), \
         patch('mercury.services.identity_service.get_session_direct', side_effect=TestSession), \
         patch('mercury.services.settings_service.get_session_direct', side_effect=TestSession), \
         patch.dict(os.environ, {'API_KEYS': 'test_api_key'}):

        MockRepo.return_value.get_admins.return_value = [MagicMock()]
        app = create_app(config={
            'TESTING': True, 'WTF_CSRF_ENABLED': False, 'LOGIN_DISABLED': True,
        })
        yield app


@pytest.fixture
def client_no_login(app_no_login):
    return app_no_login.test_client()


@pytest.mark.asyncio
async def test_smtp_service_check_all_health_success(db_session):
    """Test SMTPService.check_all_health when connection succeeds."""
    # Insert a test SMTP server
    server = SMTPServer(
        name="test-health-ok",
        host="smtp.example.com",
        port=587,
        username="test@example.com",
        _password="encrypted_pass",
        status=SMTPServerStatus.ERROR.value,  # Starts in error
        is_enabled=True,
        settings={"health_error": "Prev failure", "last_checked_at": "yesterday"}
    )
    db_session.add(server)
    db_session.commit()

    service = SMTPService()
    # Mock load_from_database to return our test server config
    service.load_from_database = MagicMock(return_value=[
        MagicMock(name="test-health-ok")
    ])
    service._configs = [
        MagicMock()
    ]
    service._configs[0].name = "test-health-ok"

    # Mock test_connection to return success
    mock_test_conn = AsyncMock(return_value={
        'success': True,
        'server': "test-health-ok",
        'host': "smtp.example.com",
        'port': 587,
        'tls_mode': "starttls",
        'auth_verified': True,
        'message': 'Connection + AUTH verified'
    })
    
    with patch.object(service, 'test_connection', mock_test_conn), \
         patch('mercury.data.database.get_session_direct', return_value=db_session), \
         patch('mercury.web.extensions.queue_emit') as mock_emit:
         
        results = await service.check_all_health()
        
        assert len(results) == 1
        assert results[0]['success'] is True
        
        # Verify server state is updated to active in DB
        db_session.expire_all()
        updated_server = db_session.query(SMTPServer).filter_by(name="test-health-ok").first()
        assert updated_server.status == SMTPServerStatus.ACTIVE.value
        assert "health_error" not in updated_server.settings
        assert "last_checked_at" in updated_server.settings
        
        # Verify Socket.IO broadcast was called
        mock_emit.assert_called_once()


@pytest.mark.asyncio
async def test_smtp_service_check_all_health_failure(db_session):
    """Test SMTPService.check_all_health when connection fails."""
    server = SMTPServer(
        name="test-health-fail",
        host="smtp.bad.com",
        port=587,
        username="bad@example.com",
        _password="encrypted_pass",
        status=SMTPServerStatus.ACTIVE.value,  # Starts active
        is_enabled=True,
        settings={}
    )
    db_session.add(server)
    db_session.commit()

    service = SMTPService()
    service._configs = [
        MagicMock()
    ]
    service._configs[0].name = "test-health-fail"

    # Mock test_connection to return failure
    mock_test_conn = AsyncMock(return_value={
        'success': False,
        'server': "test-health-fail",
        'host': "smtp.bad.com",
        'port': 587,
        'error_type': "auth_failed",
        'error': "Authentication rejected (535)",
        'details': "Incorrect credentials"
    })
    
    with patch.object(service, 'test_connection', mock_test_conn), \
         patch('mercury.data.database.get_session_direct', return_value=db_session), \
         patch('mercury.web.extensions.queue_emit') as mock_emit:
         
        results = await service.check_all_health()
        
        assert len(results) == 1
        assert results[0]['success'] is False
        
        # Verify server state is updated to error in DB
        db_session.expire_all()
        updated_server = db_session.query(SMTPServer).filter_by(name="test-health-fail").first()
        assert updated_server.status == SMTPServerStatus.ERROR.value
        assert updated_server.settings["health_error"] == "Authentication rejected (535)"
        assert updated_server.settings["health_error_type"] == "auth_failed"
        assert updated_server.settings["health_details"] == "Incorrect credentials"
        assert "last_checked_at" in updated_server.settings


def test_api_smtp_health_routes(client_no_login, db_session):
    """Test the GET /api/smtp/health and POST /api/smtp/health/check endpoints."""
    # Setup test server in SQLite DB
    server = SMTPServer(
        name="test-api-health",
        host="smtp.example.com",
        port=587,
        username="test@example.com",
        _password="encrypted_pass",
        status=SMTPServerStatus.ACTIVE.value,
        is_enabled=True,
        settings={"last_checked_at": "2026-05-28T12:00:00Z", "health_error": "some_err"}
    )
    db_session.add(server)
    db_session.commit()

    # Test GET /api/smtp/health (with X-API-Key header)
    response = client_no_login.get('/api/smtp/health', headers={'X-API-Key': 'test_api_key'})
    assert response.status_code == 200
    data = response.get_json()
    assert "servers" in data
    assert len(data["servers"]) == 1
    s_info = data["servers"][0]
    assert s_info["name"] == "test-api-health"
    assert s_info["status"] == "active"
    assert s_info["last_checked_at"] == "2026-05-28T12:00:00Z"
    assert s_info["health_error"] == "some_err"

    # Test POST /api/smtp/health/check trigger (with X-API-Key header)
    # Mock SMTPService.check_all_health to return mock results
    mock_results = [{'server': 'test-api-health', 'success': True}]
    with patch('mercury.web.routes.api.smtp.SMTPService') as MockServiceClass:
        mock_instance = MockServiceClass.return_value
        mock_instance.check_all_health = AsyncMock(return_value=mock_results)
        
        response = client_no_login.post('/api/smtp/health/check', headers={'X-API-Key': 'test_api_key'})
        assert response.status_code == 200
        res_json = response.get_json()
        assert res_json["success"] is True
        assert res_json["results"] == mock_results


def test_api_smtp_list_metrics_synchronization(client_no_login, db_session):
    """Test that GET /api/smtp correctly aggregates sent and failed counts from EmailLog and updates database."""
    # 1. Create a test SMTP server
    server = SMTPServer(
        name="metrics-test-server",
        host="smtp.metrics.com",
        port=587,
        status="active",
        is_enabled=True,
        total_sent=0,
        total_failed=0
    )
    db_session.add(server)
    db_session.commit()
    
    # 2. Add some EmailLogs for this server (both successes and failures)
    from mercury.data.models.email_log import EmailLog, EmailStatus
    
    # 2 successes
    for i in range(2):
        log_ok = EmailLog(
            recipient_email=f"ok{i}@example.com",
            status=EmailStatus.SENT.value,
            smtp_server_name="metrics-test-server"
        )
        db_session.add(log_ok)
        
    # 1 failure
    log_fail = EmailLog(
        recipient_email="fail@example.com",
        status=EmailStatus.FAILED.value,
        smtp_server_name="metrics-test-server"
    )
    db_session.add(log_fail)
    db_session.commit()
    
    # 3. Call the GET /api/smtp endpoint
    response = client_no_login.get('/api/smtp', headers={'X-API-Key': 'test_api_key'})
    assert response.status_code == 200
    data = response.get_json()
    
    # 4. Assert response matches EmailLog aggregates
    assert "servers" in data
    server_data = next(s for s in data["servers"] if s["name"] == "metrics-test-server")
    assert server_data["total_sent"] == 2
    assert server_data["total_failed"] == 1
    
    # 5. Assert the columns have been committed and persisted in the database
    db_session.expire_all()
    db_server = db_session.query(SMTPServer).filter_by(name="metrics-test-server").first()
    assert db_server.total_sent == 2
    assert db_server.total_failed == 1


@pytest.mark.asyncio
async def test_smtp_service_check_server_health_success(db_session):
    """Test SMTPService.check_server_health when connection succeeds."""
    server = SMTPServer(
        name="test-single-ok",
        host="smtp.example.com",
        port=587,
        username="test@example.com",
        _password="encrypted_pass",
        status=SMTPServerStatus.ERROR.value,
        is_enabled=True,
        settings={"health_error": "Prev failure", "last_checked_at": "yesterday"}
    )
    db_session.add(server)
    db_session.commit()

    service = SMTPService()
    service._configs = [MagicMock()]
    service._configs[0].name = "test-single-ok"

    mock_test_conn = AsyncMock(return_value={
        'success': True,
        'server': "test-single-ok",
        'host': "smtp.example.com",
        'port': 587,
        'tls_mode': "starttls",
        'auth_verified': True,
        'message': 'Connection + AUTH verified'
    })
    
    with patch.object(service, 'test_connection', mock_test_conn), \
         patch('mercury.data.database.get_session_direct', return_value=db_session), \
         patch('mercury.web.extensions.queue_emit') as mock_emit:
         
        result = await service.check_server_health("test-single-ok")
        
        assert result['success'] is True
        
        db_session.expire_all()
        updated_server = db_session.query(SMTPServer).filter_by(name="test-single-ok").first()
        assert updated_server.status == SMTPServerStatus.ACTIVE.value
        assert "health_error" not in updated_server.settings
        assert "last_checked_at" in updated_server.settings
        mock_emit.assert_called_once()


@pytest.mark.asyncio
async def test_smtp_service_check_server_health_failure(db_session):
    """Test SMTPService.check_server_health when connection fails."""
    server = SMTPServer(
        name="test-single-fail",
        host="smtp.bad.com",
        port=587,
        username="bad@example.com",
        _password="encrypted_pass",
        status=SMTPServerStatus.ACTIVE.value,
        is_enabled=True,
        settings={}
    )
    db_session.add(server)
    db_session.commit()

    service = SMTPService()
    service._configs = [MagicMock()]
    service._configs[0].name = "test-single-fail"

    mock_test_conn = AsyncMock(return_value={
        'success': False,
        'server': "test-single-fail",
        'host': "smtp.bad.com",
        'port': 587,
        'error_type': "auth_failed",
        'error': "Authentication rejected (535)",
        'details': "Incorrect credentials"
    })
    
    with patch.object(service, 'test_connection', mock_test_conn), \
         patch('mercury.data.database.get_session_direct', return_value=db_session), \
         patch('mercury.web.extensions.queue_emit') as mock_emit:
         
        result = await service.check_server_health("test-single-fail")
        
        assert result['success'] is False
        
        db_session.expire_all()
        updated_server = db_session.query(SMTPServer).filter_by(name="test-single-fail").first()
        assert updated_server.status == SMTPServerStatus.ERROR.value
        assert updated_server.settings["health_error"] == "Authentication rejected (535)"
        assert updated_server.settings["health_error_type"] == "auth_failed"
        assert updated_server.settings["health_details"] == "Incorrect credentials"
        assert "last_checked_at" in updated_server.settings
        mock_emit.assert_called_once()

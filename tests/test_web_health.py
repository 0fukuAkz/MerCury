"""Tests for Web App Health Checks."""

import pytest
from unittest.mock import patch, Mock, MagicMock
from unified_sender.web.app import create_app

@pytest.fixture
def app():
    app = create_app()
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    return app

@pytest.fixture
def client(app):
    return app.test_client()

@pytest.fixture
def mock_auth():
    with patch('unified_sender.web.app.current_user') as mock_user:
        mock_user.is_authenticated = True
        yield mock_user

def test_health_detailed_success(client, mock_auth):
    """Test detailed health check with all components healthy."""
    
    # Mock DB
    with patch('unified_sender.data.database.get_engine') as mock_get_engine:
        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        
        # Mock SMTP
        with patch('unified_sender.data.database.get_session_direct') as mock_limit_session, \
             patch('unified_sender.data.repositories.SMTPRepository') as MockRepo:
            
            mock_session = Mock()
            mock_limit_session.return_value = mock_session
            
            mock_repo_instance = Mock()
            MockRepo.return_value = mock_repo_instance
            mock_repo_instance.get_active.return_value = [1, 2, 3] # 3 servers
            
            # Mock Disk using shutil.disk_usage
            # Return tuple (total, used, free)
            # 100GB total, 50 used, 50 free
            free_bytes = 50 * (1024**3)
            with patch('shutil.disk_usage', return_value=(100, 50, free_bytes)):
                
                response = client.get('/health/detailed')
                
                assert response.status_code == 200
                data = response.get_json()
                
                assert data['status'] == 'healthy'


def test_health_detailed_failures(client, mock_auth):
    """Test detailed health check with component failures."""
    
    # Mock DB Failure
    with patch('unified_sender.data.database.get_engine') as mock_get_engine:
        # If we use side_effect here, connect isn't called
        mock_get_engine.side_effect = Exception("DB Connection Failed")
        
        # Mock SMTP Failure
        with patch('unified_sender.data.database.get_session_direct') as mock_limit_session:
             mock_limit_session.side_effect = Exception("SMTP DB Failed")
             
             # Mock Disk Warning (low space)
             # Free space < 1GB
             low_free = 0.5 * (1024**3)
             with patch('shutil.disk_usage', return_value=(100, 99.5, low_free)):
                 
                 response = client.get('/health/detailed')
                 
                 assert response.status_code == 200
                 data = response.get_json()
                 assert data['status'] == 'degraded'
                 
                 # Check DB
                 assert data['components']['database']['status'] == 'unhealthy'
                 assert "DB Connection Failed" in data['components']['database']['error']
                 
                 # Check SMTP
                 assert data['components']['smtp']['status'] == 'unknown'
                 assert "SMTP DB Failed" in data['components']['smtp']['error']
                 
                 # Check Disk
                 assert data['components']['disk']['status'] == 'warning'

def test_readiness_probe(client):
    """Test readiness probe endpoint."""
    # /ready checks DB using local import
    with patch('unified_sender.data.database.get_engine') as mock_get_engine:
        
        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        
        response = client.get('/ready')
        assert response.status_code == 200

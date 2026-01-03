
import pytest
import os
import secrets
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, UTC, timedelta

from mercury.security.auth import (
    User, hash_password, verify_password, authenticate, 
    require_api_key, generate_unsubscribe_token, 
    validate_unsubscribe_token, create_user
)

@pytest.fixture
def mock_user():
    return User(
        id="1",
        username="testuser",
        password_hash="salt$hash",
        email="test@example.com",
        is_admin=False
    )

class TestAuthExtended:
    """Extended tests for auth module."""

    def test_hash_verify_password(self):
        """Test password hashing and verification."""
        password = "mysecretpassword"
        
        # Test hash generation
        pw_hash = hash_password(password)
        assert "$" in pw_hash
        
        # Test verification
        assert verify_password(password, pw_hash) is True
        assert verify_password("wrongpassword", pw_hash) is False
        assert verify_password(password, "malformedhash") is False

    @patch('mercury.data.database.get_session_direct')
    @patch('mercury.security.auth.hash_password')
    def test_create_user(self, mock_hash, mock_get_session):
        """Test user creation."""
        mock_hash.return_value = "hashed_pw"
        
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session
        
        # Mock repository
        with patch('mercury.data.repositories.UserRepository') as MockRepo:
            repo_instance = MockRepo.return_value
            repo_instance.username_exists.return_value = False
            
            # Mock created user returned from repo
            db_user = MagicMock()
            db_user.id = 1
            db_user.username = "newuser"
            db_user.password_hash = "hashed_pw"
            db_user.email = "new@example.com"
            db_user.is_admin = False
            db_user.is_active = True
            db_user.created_at = datetime.now(UTC)
            db_user.last_login_at = None
            db_user.must_change_password = False
            
            repo_instance.create.return_value = db_user
            
            user = create_user("newuser", "pass", "new@example.com")
            
            assert user.username == "newuser"
            assert user.id == "1"
            repo_instance.create.assert_called_once()

    @patch('mercury.data.database.get_session_direct')
    @patch('mercury.security.auth.verify_password')
    def test_authenticate_success(self, mock_verify, mock_get_session):
        """Test successful authentication."""
        mock_verify.return_value = True
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session
        
        with patch('mercury.data.repositories.UserRepository') as MockRepo:
            repo_instance = MockRepo.return_value
            
            db_user = MagicMock()
            db_user.id = 1
            db_user.username = "user"
            db_user.password_hash = "hash"
            db_user.is_active = True
            db_user.login_count = 0
            
            repo_instance.get_by_username.return_value = db_user
            
            user = authenticate("user", "pass")
            
            assert user is not None
            assert user.username == "user"
            assert db_user.login_count == 1
            mock_session.commit.assert_called_once()

    @patch('mercury.data.database.get_session_direct')
    def test_authenticate_failure(self, mock_get_session):
        """Test authentication failures."""
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session
        
        with patch('mercury.data.repositories.UserRepository') as MockRepo:
            repo_instance = MockRepo.return_value
            
            # Case 1: User not found
            repo_instance.get_by_username.return_value = None
            assert authenticate("nonexistent", "pass") is None
            
            # Case 2: User disabled
            db_user = MagicMock()
            db_user.is_active = False
            repo_instance.get_by_username.return_value = db_user
            assert authenticate("disabled", "pass") is None

    def test_require_api_key(self):
        """Test API key validation."""
        # Test with no keys configured
        with patch.dict(os.environ, {}, clear=True):
            assert require_api_key("somekey") is False
            
        # Test with keys configured
        with patch.dict(os.environ, {"API_KEYS": "key1,key2"}):
            assert require_api_key("key1") is True
            assert require_api_key("key2") is True
            assert require_api_key("wrong") is False
            assert require_api_key("") is False

    def test_unsubscribe_tokens(self):
        """Test unsubscribe token generation and validation."""
        email = "test@example.com"
        email_id = "123"
        
        # Determine secret
        with patch.dict(os.environ, {"UNSUBSCRIBE_SECRET": "secret"}):
            token = generate_unsubscribe_token(email, email_id)
            
            # Valid token
            valid, msg = validate_unsubscribe_token(token, email_id, email)
            assert valid is True
            assert msg == ""
            
            # Invalid email_id
            valid, msg = validate_unsubscribe_token(token, "999", email)
            assert valid is False
            assert "matches" in msg or "match" in msg
            
            # Invalid email (hash check)
            valid, msg = validate_unsubscribe_token(token, email_id, "wrong@example.com")
            assert valid is False
            
            # Expired token (mocking time)
            # Need to generate an expired token manually or rely on internals, 
            # simplest is to mock datetime during validation or generation.
            # Here we mock generation to set old timestamp
            with patch('mercury.security.auth.datetime') as mock_dt:
                # Setup mock to behave like datetime
                mock_dt.now.return_value = datetime.now(UTC) - timedelta(days=2)
                mock_dt.UTC = UTC
                
                # We can't easily use the public function to generate expired token 
                # because it adds expires_days.
                # So we manually create expired token logic or use negative expires_days if allowed.
                # The function allows expires_days param.
                
                token_expired = generate_unsubscribe_token(email, email_id, expires_days=-1)
                
            valid, msg = validate_unsubscribe_token(token_expired, email_id, email)
            assert valid is False
            assert "expired" in msg

    def test_user_properties(self, mock_user):
        """Test User class properties."""
        assert mock_user.is_authenticated is True  # UserMixin default
        assert mock_user.is_active is True
        assert mock_user.is_anonymous is False
        assert mock_user.get_id() == "1"

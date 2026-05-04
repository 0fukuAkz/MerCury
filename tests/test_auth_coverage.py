"""Tests for auth.py coverage."""

from mercury.security.auth import (
    authenticate, require_api_key, generate_unsubscribe_token, validate_unsubscribe_token,
    create_user, load_user
)

def test_require_api_key(monkeypatch):
    assert require_api_key("") is False
    
    # No keys configured
    monkeypatch.delenv("API_KEYS", raising=False)
    assert require_api_key("secret") is False
    
    # Comma separated
    monkeypatch.setenv("API_KEYS", "key1,key2")
    assert require_api_key("key1") is True
    assert require_api_key("key2") is True
    assert require_api_key("key3") is False
    
    # Shell style
    monkeypatch.setenv("API_KEYS", '"key with spaces" key2')
    assert require_api_key("key with spaces") is True

def test_authenticate_invalid_user(app):
    # Should perform dummy hash and return None
    assert authenticate("nonexistent", "password") is None

def test_authenticate_disabled_user(app, db_session):
    from mercury.data.models import User as DBUser
    create_user("disabled", "pass", is_admin=False)
    db_user = db_session.query(DBUser).filter_by(username="disabled").first()
    if db_user:
        db_user.is_active = False
        db_session.commit()
        
    assert authenticate("disabled", "pass") is None

def test_authenticate_wrong_password(app, db_session):
    create_user("wrongpass", "pass")
    assert authenticate("wrongpass", "wrong") is None

def test_authenticate_success(app, db_session):
    create_user("gooduser", "pass")
    user = authenticate("gooduser", "pass")
    assert user is not None
    assert user.username == "gooduser"

def test_unsubscribe_tokens():
    email = "test@example.com"
    email_id = "12345"
    token = generate_unsubscribe_token(email, email_id)
    
    is_valid, msg = validate_unsubscribe_token(token, email_id)
    assert is_valid is True
    
    # Invalid email_id
    is_valid, msg = validate_unsubscribe_token(token, "99999")
    assert is_valid is False
    
    # Invalid format
    is_valid, _ = validate_unsubscribe_token("invalid", email_id)
    assert is_valid is False

def test_load_user(app, db_session):
    user = create_user("loader", "pass")
    loaded = load_user(str(user.id))
    assert loaded is not None
    assert loaded.username == "loader"
    
    assert load_user("99999") is None

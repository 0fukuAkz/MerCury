"""Tests for encryption.py coverage."""

import pytest
import os
from unittest.mock import patch
from mercury.security.encryption import EncryptionService, get_encryption_service

def test_encryption_lifecycle():
    # Test with password
    svc = EncryptionService(password="secret")
    plain = "Hello World"
    cipher = svc.encrypt(plain)
    assert cipher != plain
    assert svc.decrypt(cipher) == plain
    
    # Test encrypt_if_needed
    c2 = svc.encrypt_if_needed(plain)
    assert svc.is_encrypted(c2)
    assert svc.encrypt_if_needed(c2) == c2
    
    # Test decrypt_if_needed
    assert svc.decrypt_if_needed(plain) == plain
    assert svc.decrypt_if_needed(c2) == plain

def test_encryption_failure():
    svc = EncryptionService(password="p1")
    svc2 = EncryptionService(password="p2")
    
    cipher = svc.encrypt("test")
    with pytest.raises(ValueError, match="Decryption failed"):
        svc2.decrypt(cipher)

def test_encryption_env_loading(monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", EncryptionService.generate_key().decode())
    svc = EncryptionService()
    assert svc._key is not None
    
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("ENCRYPTION_PASSWORD", "envpass")
    svc2 = EncryptionService()
    assert svc2._key is not None

def test_encryption_ephemeral_fallback():
    with patch('mercury.security.encryption.os.environ.get', return_value=None):
        svc = EncryptionService()
        assert svc._key is not None

def test_encryption_global_service():
    svc = get_encryption_service()
    assert isinstance(svc, EncryptionService)
    assert get_encryption_service() is svc

def test_encryption_empty_values():
    svc = EncryptionService(password="test")
    assert svc.encrypt("") == ""
    assert svc.decrypt("") == ""
    assert svc.is_encrypted(None) is False

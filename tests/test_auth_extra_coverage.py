"""Tests for auth.py extra coverage.

Targets missing lines:
  58, 71, 75, 79, 167-169, 204, 241-242, 249-262,
  330-365, 395-397, 539-540.
"""

import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, UTC, timedelta
from unittest.mock import MagicMock, patch

import pytest

from mercury.security.auth import (
    User,
    hash_password,
    verify_password,
    create_user,
    get_user_by_id,
    get_user_by_username,
    generate_unsubscribe_token,
    validate_unsubscribe_token,
    init_auth,
    require_api_key,
    _get_unsubscribe_secret,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(**kwargs) -> User:
    defaults = dict(
        id="42",
        username="testuser",
        password_hash=hash_password("secret"),
        email="test@example.com",
        is_admin=False,
        is_active=True,
    )
    defaults.update(kwargs)
    return User(**defaults)


# ---------------------------------------------------------------------------
# User.is_admin property  (line 58)
# ---------------------------------------------------------------------------

class TestUserIsAdmin:
    def test_is_admin_false_by_default(self):
        u = _make_user(is_admin=False)
        assert u.is_admin is False

    def test_is_admin_true(self):
        u = _make_user(is_admin=True)
        assert u.is_admin is True


# ---------------------------------------------------------------------------
# User.check_password  (line 71)
# ---------------------------------------------------------------------------

class TestUserCheckPassword:
    def test_check_password_correct(self):
        """Line 71: delegates to verify_password; should return True."""
        u = _make_user(password_hash=hash_password("mypass"))
        assert u.check_password("mypass") is True

    def test_check_password_wrong(self):
        u = _make_user(password_hash=hash_password("mypass"))
        assert u.check_password("wrongpass") is False


# ---------------------------------------------------------------------------
# User.set_password  (line 75)
# ---------------------------------------------------------------------------

class TestUserSetPassword:
    def test_set_password_updates_hash(self):
        """Line 75: password_hash attribute must change."""
        u = _make_user(password_hash=hash_password("old"))
        old_hash = u.password_hash
        u.set_password("newpass")
        assert u.password_hash != old_hash
        assert u.check_password("newpass") is True

    def test_set_password_old_no_longer_valid(self):
        u = _make_user(password_hash=hash_password("old"))
        u.set_password("new")
        assert u.check_password("old") is False


# ---------------------------------------------------------------------------
# User.to_dict  (line 79)
# ---------------------------------------------------------------------------

class TestUserToDict:
    def test_to_dict_contains_all_fields(self):
        """Line 79: to_dict must include all declared keys."""
        now = datetime.now(UTC)
        u = User(
            id="7",
            username="alice",
            password_hash="x$y",
            email="alice@example.com",
            is_admin=True,
            is_active=False,
            created_at=now,
            last_login=now,
            must_change_password=True,
        )
        d = u.to_dict()
        assert d["id"] == "7"
        assert d["username"] == "alice"
        assert d["email"] == "alice@example.com"
        assert d["is_admin"] is True
        assert d["is_active"] is False
        assert d["must_change_password"] is True
        assert d["created_at"] is not None
        assert d["last_login"] is not None

    def test_to_dict_none_last_login(self):
        u = _make_user(last_login=None)
        d = u.to_dict()
        assert d["last_login"] is None


# ---------------------------------------------------------------------------
# verify_password with invalid hash format  (lines 167-169)
# ---------------------------------------------------------------------------

class TestVerifyPasswordInvalidHash:
    def test_returns_false_when_no_dollar_sign(self):
        """Lines 151-152, 167-169: hash without '$' must return False."""
        assert verify_password("pass", "nodollarsign") is False

    def test_returns_false_on_bad_base64(self):
        """Lines 167-169: invalid base64 triggers the except branch."""
        assert verify_password("pass", "!!!$???") is False

    def test_returns_false_on_three_parts(self):
        """More than two '$'-separated parts is also invalid."""
        assert verify_password("pass", "a$b$c") is False


# ---------------------------------------------------------------------------
# create_user with duplicate username  (line 204)
# ---------------------------------------------------------------------------

class TestCreateUserDuplicate:
    def test_duplicate_username_raises_value_error(self, app):
        """Line 204: creating a user with a taken username must raise ValueError."""
        create_user("unique_user_dup", "pass1")
        with pytest.raises(ValueError, match="already exists"):
            create_user("unique_user_dup", "pass2")


# ---------------------------------------------------------------------------
# get_user_by_id with non-integer id  (lines 241-242)
# ---------------------------------------------------------------------------

class TestGetUserById:
    def test_non_integer_id_returns_none(self, app):
        """Lines 241-242: ValueError/TypeError must be caught and None returned."""
        result = get_user_by_id("not-an-int")
        assert result is None

    def test_none_id_returns_none(self, app):
        result = get_user_by_id(None)
        assert result is None

    def test_valid_nonexistent_id_returns_none(self, app):
        result = get_user_by_id("999999")
        assert result is None

    def test_valid_existing_id_returns_user(self, app):
        u = create_user("id_lookup_user", "pass")
        result = get_user_by_id(u.id)
        assert result is not None
        assert result.username == "id_lookup_user"


# ---------------------------------------------------------------------------
# get_user_by_username  (lines 249-262)
# ---------------------------------------------------------------------------

class TestGetUserByUsername:
    def test_returns_none_for_unknown_username(self, app):
        """Lines 249-262: unknown username yields None."""
        result = get_user_by_username("completely_unknown_xyz")
        assert result is None

    def test_returns_user_for_known_username(self, app):
        create_user("known_user_abc", "pass")
        result = get_user_by_username("known_user_abc")
        assert result is not None
        assert result.username == "known_user_abc"

    def test_returned_user_is_user_instance(self, app):
        create_user("type_check_user", "pass")
        result = get_user_by_username("type_check_user")
        assert isinstance(result, User)


# ---------------------------------------------------------------------------
# init_auth  (lines 330-365)
# ---------------------------------------------------------------------------

class TestInitAuth:
    # init_auth imports init_db and get_session_direct inside the function body,
    # so we patch them at their source location (mercury.data.database /
    # mercury.data.repositories) rather than on the auth module.

    def test_init_auth_creates_admin_when_env_vars_set(self, monkeypatch):
        """Lines 350-358: admin is created when ADMIN_USERNAME/PASSWORD are set."""
        monkeypatch.setenv("ADMIN_USERNAME", "envadmin")
        monkeypatch.setenv("ADMIN_PASSWORD", "envpass")
        monkeypatch.setenv("ADMIN_EMAIL", "envadmin@localhost")

        mock_app = MagicMock()

        mock_session = MagicMock()
        mock_repo = MagicMock()
        mock_repo.get_admins.return_value = []  # no admins yet

        with patch("mercury.security.auth.login_manager"), \
             patch("mercury.data.database.init_db"), \
             patch("mercury.data.database.get_session_direct", return_value=mock_session), \
             patch("mercury.data.repositories.UserRepository", return_value=mock_repo), \
             patch("mercury.security.auth.create_user") as mock_create:

            init_auth(mock_app)

            mock_create.assert_called_once_with(
                username="envadmin",
                password="envpass",
                email="envadmin@localhost",
                is_admin=True,
                must_change_password=True,
            )

    def test_init_auth_logs_warning_when_no_env_and_no_admins(self, monkeypatch, caplog):
        """Lines 359-363: warning is logged when no admin exists and no env vars."""
        monkeypatch.delenv("ADMIN_USERNAME", raising=False)
        monkeypatch.delenv("ADMIN_PASSWORD", raising=False)

        mock_app = MagicMock()
        mock_session = MagicMock()
        mock_repo = MagicMock()
        mock_repo.get_admins.return_value = []

        with patch("mercury.security.auth.login_manager"), \
             patch("mercury.data.database.init_db"), \
             patch("mercury.data.database.get_session_direct", return_value=mock_session), \
             patch("mercury.data.repositories.UserRepository", return_value=mock_repo):

            import logging
            with caplog.at_level(logging.WARNING, logger="mercury.security.auth"):
                init_auth(mock_app)

        assert "ADMIN_USERNAME" in caplog.text or "inaccessible" in caplog.text

    def test_init_auth_skips_create_when_admin_exists(self):
        """Lines 344-345: when admins already exist, create_user must not be called."""
        mock_app = MagicMock()
        mock_session = MagicMock()
        mock_repo = MagicMock()
        mock_repo.get_admins.return_value = [MagicMock()]  # admin exists

        with patch("mercury.security.auth.login_manager"), \
             patch("mercury.data.database.init_db"), \
             patch("mercury.data.database.get_session_direct", return_value=mock_session), \
             patch("mercury.data.repositories.UserRepository", return_value=mock_repo), \
             patch("mercury.security.auth.create_user") as mock_create:

            init_auth(mock_app)

            mock_create.assert_not_called()


# ---------------------------------------------------------------------------
# require_api_key with shlex exception  (lines 395-397)
# ---------------------------------------------------------------------------

class TestRequireApiKeyShlex:
    def test_shlex_exception_returns_false(self, monkeypatch):
        """Lines 395-397: when shlex.split raises, fallback is empty list -> False.

        require_api_key imports shlex inline and calls shlex.split.  Patching the
        shlex module's split function directly simulates a bad-quoting error.
        """
        monkeypatch.setenv("API_KEYS", "somekey")

        # shlex is imported inside the function body via `import shlex`, so we
        # patch the actual shlex.split in the standard library module which is
        # what the function references at call time.
        with patch("shlex.split", side_effect=ValueError("bad quoting")):
            result = require_api_key("somekey")

        # With empty valid_keys fallback the function must return False
        assert result is False


# ---------------------------------------------------------------------------
# validate_unsubscribe_token edge cases  (lines 503-504, 539-540)
# ---------------------------------------------------------------------------

class TestValidateUnsubscribeToken:
    def _valid_token(self, email="user@example.com", email_id="111"):
        return generate_unsubscribe_token(email, email_id, expires_days=1)

    def test_empty_token_returns_false(self):
        """Line 503-504: empty string returns (False, 'Missing token')."""
        valid, msg = validate_unsubscribe_token("", "111")
        assert valid is False
        assert "Missing" in msg

    def test_none_token_returns_false(self):
        valid, msg = validate_unsubscribe_token(None, "111")
        assert valid is False

    def test_bad_signature_returns_false(self):
        """Lines 538-540: tampered signature yields 'Invalid token signature'."""
        token = self._valid_token(email_id="222")
        # Decode, replace last character of signature, re-encode
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        parts = raw.split("|")
        # Corrupt the signature (4th part)
        parts[3] = parts[3][:-1] + ("X" if parts[3][-1] != "X" else "Y")
        tampered = base64.urlsafe_b64encode("|".join(parts).encode()).decode()

        valid, msg = validate_unsubscribe_token(tampered, "222")
        assert valid is False
        assert "signature" in msg.lower() or "invalid" in msg.lower()

    def test_email_hash_mismatch_returns_false(self):
        """Lines 543-547: correct token but wrong email triggers hash mismatch."""
        token = self._valid_token(email="real@example.com", email_id="333")
        valid, msg = validate_unsubscribe_token(
            token, "333", email="other@example.com"
        )
        assert valid is False
        assert "email" in msg.lower() or "address" in msg.lower()

    def test_expired_token_returns_false(self):
        """Lines 524-525: token past its expiry timestamp must be rejected."""
        secret = _get_unsubscribe_secret()
        # Build an already-expired token manually
        email = "expire@example.com"
        email_id = "999"
        expired_ts = int((datetime.now(UTC) - timedelta(days=1)).timestamp())
        email_hash = hashlib.sha256(email.lower().encode()).hexdigest()[:16]
        payload = f"{email_id}|{email_hash}|{expired_ts}"
        signature = hmac.new(
            secret, payload.encode("utf-8"), hashlib.sha256
        ).hexdigest()[:32]
        token_data = f"{payload}|{signature}"
        token = base64.urlsafe_b64encode(token_data.encode()).decode()

        valid, msg = validate_unsubscribe_token(token, email_id)
        assert valid is False
        assert "expired" in msg.lower()

    def test_invalid_format_wrong_part_count(self):
        """Lines 511-512: token that does not decode to 4 parts."""
        # Encode something with only 2 parts
        raw = "justtwothings|here"
        token = base64.urlsafe_b64encode(raw.encode()).decode()
        valid, msg = validate_unsubscribe_token(token, "any")
        assert valid is False
        assert "format" in msg.lower() or "invalid" in msg.lower()

    def test_email_id_mismatch_returns_false(self):
        """Lines 517-519: email_id in token does not match supplied email_id."""
        token = self._valid_token(email_id="abc")
        valid, msg = validate_unsubscribe_token(token, "different_id")
        assert valid is False

    def test_valid_token_returns_true(self):
        """Sanity check: a freshly generated token must validate successfully."""
        email = "ok@example.com"
        email_id = "555"
        token = generate_unsubscribe_token(email, email_id)
        valid, msg = validate_unsubscribe_token(token, email_id, email=email)
        assert valid is True
        assert msg == ""

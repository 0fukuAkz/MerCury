"""
Coverage tests for mercury.data.models:
  - template.py
  - smtp.py
  - recipient.py
  - campaign.py
  - base.py
  - user.py
  - email_log.py
  - dead_letter.py
  - identity.py
  - settings.py
"""

from datetime import datetime, UTC
from unittest.mock import patch, MagicMock

from mercury.data.models import (
    Template,
    SMTPServer,
    SMTPServerStatus,
    RecipientList,
    Recipient,
    Campaign,
    CampaignStatus,
    EmailLog,
    EmailStatus,
    User,
    FromEmail,
    SenderName,
    GlobalSetting,
    DeadLetter,
    BaseModel,
)


# ---------------------------------------------------------------------------
# Template model (template.py lines 47-60)
# ---------------------------------------------------------------------------


class TestTemplateModel:
    """Tests for Template model methods."""

    def test_get_html_with_html_content(self):
        """Line 47-48: returns html_content when set."""
        tmpl = Template()
        tmpl.html_content = "<p>Direct content</p>"
        assert tmpl.get_html() == "<p>Direct content</p>"

    def test_get_html_with_html_path(self, tmp_path):
        """Lines 50-55: reads from html_path when html_content is not set."""
        html_file = tmp_path / "email.html"
        html_file.write_text("<p>From file</p>")
        tmpl = Template()
        tmpl.html_content = None
        tmpl.html_path = str(html_file)
        assert tmpl.get_html() == "<p>From file</p>"

    def test_get_html_with_invalid_html_path(self):
        """Lines 50-55: bad html_path falls through to '' (exception swallowed)."""
        tmpl = Template()
        tmpl.html_content = None
        tmpl.html_path = "/tmp/__nonexistent_file_xyz__.html"
        assert tmpl.get_html() == ""

    def test_get_html_with_neither(self):
        """Line 57: no content and no path returns ''."""
        tmpl = Template()
        tmpl.html_content = None
        tmpl.html_path = None
        assert tmpl.get_html() == ""

    def test_repr(self):
        """Line 59-60: __repr__ format."""
        tmpl = Template()
        tmpl.id = 7
        tmpl.name = "Welcome Email"
        result = repr(tmpl)
        assert "Template" in result
        assert "7" in result
        assert "Welcome Email" in result


# ---------------------------------------------------------------------------
# SMTPServer model (smtp.py lines 68-138)
# ---------------------------------------------------------------------------


class TestSMTPServerModel:
    """Tests for SMTPServer model properties and methods."""

    def test_password_getter_no_password(self):
        """Lines 71-72: empty _password returns ''."""
        server = SMTPServer()
        server._password = None
        assert server.password == ""

    def test_password_getter_with_encryption_service(self):
        """Lines 74-77: decrypts via encryption service when _password set."""
        server = SMTPServer()
        server._password = "encrypted_value"
        mock_service = MagicMock()
        mock_service.decrypt_if_needed.return_value = "plaintext"
        # The getter does a local import: `from ...security.encryption import get_encryption_service`
        # so we patch the function on the actual module object at call time.
        with patch("mercury.security.encryption.get_encryption_service", return_value=mock_service):
            assert server.password == "plaintext"
            mock_service.decrypt_if_needed.assert_called_once_with("encrypted_value")

    def test_password_getter_decryption_failure_returns_raw(self):
        """Lines 78-80: if decryption fails, returns _password as-is."""
        server = SMTPServer()
        server._password = "raw_password"
        with patch(
            "mercury.security.encryption.get_encryption_service",
            side_effect=Exception("no key"),
        ):
            assert server.password == "raw_password"

    def test_password_setter_empty_string(self):
        """Lines 85-87: setting empty password stores ''."""
        server = SMTPServer()
        server.password = ""
        assert server._password == ""

    def test_password_setter_encrypts(self):
        """Lines 89-92: setter encrypts the value."""
        server = SMTPServer()
        mock_service = MagicMock()
        mock_service.encrypt.return_value = "encrypted_abc"
        with patch("mercury.security.encryption.get_encryption_service", return_value=mock_service):
            server.password = "secret"
            assert server._password == "encrypted_abc"
            mock_service.encrypt.assert_called_once_with("secret")

    def test_password_setter_encryption_failure_raises(self):
        """Encryption failure must raise — never silently persist plaintext.

        Older behavior fell back to storing the raw value, which silently
        leaked secrets into the DB if the encryption service was misconfigured.
        The setter now raises RuntimeError so the API layer can surface the
        error to the operator instead.
        """
        import pytest

        server = SMTPServer()
        with patch(
            "mercury.security.encryption.get_encryption_service",
            side_effect=Exception("no key"),
        ):
            with pytest.raises(RuntimeError, match="encryption failed"):
                server.password = "fallback_plain"
            # Ensure we did not silently persist plaintext on the failure path.
            assert server._password in (None, "")

    def test_success_rate_zero_total(self):
        """Lines 100-102: 0 total → 100.0%."""
        server = SMTPServer()
        server.total_sent = 0
        server.total_failed = 0
        assert server.success_rate == 100.0

    def test_success_rate_with_values(self):
        """Lines 103: non-zero totals compute correctly."""
        server = SMTPServer()
        server.total_sent = 90
        server.total_failed = 10
        assert server.success_rate == 90.0

    def test_is_available_true(self):
        """Lines 107-112: enabled, ACTIVE, circuit open=False → True."""
        server = SMTPServer()
        server.is_enabled = True
        server.status = SMTPServerStatus.ACTIVE.value
        server.circuit_open = False
        assert server.is_available is True

    def test_is_available_disabled(self):
        """is_enabled=False → not available."""
        server = SMTPServer()
        server.is_enabled = False
        server.status = SMTPServerStatus.ACTIVE.value
        server.circuit_open = False
        assert server.is_available is False

    def test_is_available_circuit_open(self):
        """circuit_open=True → not available."""
        server = SMTPServer()
        server.is_enabled = True
        server.status = SMTPServerStatus.ACTIVE.value
        server.circuit_open = True
        assert server.is_available is False

    def test_is_available_wrong_status(self):
        """Non-ACTIVE status → not available."""
        server = SMTPServer()
        server.is_enabled = True
        server.status = SMTPServerStatus.ERROR.value
        server.circuit_open = False
        assert server.is_available is False

    def test_get_connection_config(self):
        """Lines 114-127: returns dict with expected keys."""
        server = SMTPServer()
        server.host = "smtp.example.com"
        server.port = 587
        server.username = "user@example.com"
        server._password = None
        server.tls_mode = "starttls"
        server.use_auth = True
        server.timeout = 30
        server.from_email = "from@example.com"
        server.from_name = "Sender"

        config = server.get_connection_config()
        assert config["host"] == "smtp.example.com"
        assert config["port"] == 587
        assert config["tls_mode"] == "starttls"
        assert "password" in config
        assert "from_email" in config

    def test_repr(self):
        """Line 138: __repr__ format."""
        server = SMTPServer()
        server.id = 3
        server.name = "primary"
        server.host = "mail.example.com"
        result = repr(server)
        assert "SMTPServer" in result
        assert "3" in result
        assert "primary" in result
        assert "mail.example.com" in result


# ---------------------------------------------------------------------------
# RecipientList and Recipient models (recipient.py)
# ---------------------------------------------------------------------------


class TestRecipientListModel:
    """Tests for RecipientList __repr__ (line 54)."""

    def test_repr(self):
        """Line 54: __repr__ format."""
        rl = RecipientList()
        rl.id = 11
        rl.name = "Newsletter List"
        rl.total_count = 500
        result = repr(rl)
        assert "RecipientList" in result
        assert "11" in result
        assert "Newsletter List" in result
        assert "500" in result


class TestRecipientModel:
    """Tests for Recipient properties and methods."""

    def test_full_name_with_first_and_last(self):
        """Lines 89-91: returns 'First Last'."""
        r = Recipient()
        r.first_name = "John"
        r.last_name = "Doe"
        r.local_part = "john.doe"
        assert r.full_name == "John Doe"

    def test_full_name_with_first_only(self):
        """Lines 89-91: only first name."""
        r = Recipient()
        r.first_name = "Alice"
        r.last_name = None
        r.local_part = "alice"
        assert r.full_name == "Alice"

    def test_full_name_no_names_falls_back_to_local_part(self):
        """Lines 89-91: no first/last → local_part.capitalize()."""
        r = Recipient()
        r.first_name = None
        r.last_name = None
        r.local_part = "jsmith"
        assert r.full_name == "Jsmith"

    def test_get_placeholders_without_custom_data(self):
        """Lines 94-108: returns expected keys, no custom_data."""
        r = Recipient()
        r.email = "bob@example.com"
        r.local_part = "bob"
        r.domain = "example.com"
        r.domain_name = "example"
        r.first_name = "Bob"
        r.last_name = "Smith"
        r.company = "Acme"
        r.custom_data = None

        ph = r.get_placeholders()
        assert ph["email"] == "bob@example.com"
        assert ph["first_name"] == "Bob"
        assert ph["full_name"] == "Bob Smith"
        assert ph["company"] == "Acme"

    def test_get_placeholders_with_custom_data(self):
        """Lines 106-107: custom_data merged into placeholders."""
        r = Recipient()
        r.email = "carol@example.com"
        r.local_part = "carol"
        r.domain = "example.com"
        r.domain_name = "example"
        r.first_name = "Carol"
        r.last_name = ""
        r.company = ""
        r.custom_data = {"promo_code": "SAVE20", "tier": "gold"}

        ph = r.get_placeholders()
        assert ph["promo_code"] == "SAVE20"
        assert ph["tier"] == "gold"

    def test_get_placeholders_first_name_falls_back_to_local_part(self):
        """Line 100: first_name None → local_part.capitalize()."""
        r = Recipient()
        r.email = "dave@example.com"
        r.local_part = "dave"
        r.domain = "example.com"
        r.domain_name = "example"
        r.first_name = None
        r.last_name = None
        r.company = None
        r.custom_data = None

        ph = r.get_placeholders()
        assert ph["first_name"] == "Dave"

    def test_repr(self):
        """Line 112: __repr__ format."""
        r = Recipient()
        r.id = 42
        r.email = "test@example.com"
        result = repr(r)
        assert "Recipient" in result
        assert "42" in result
        assert "test@example.com" in result


# ---------------------------------------------------------------------------
# Campaign model (campaign.py lines 100-118)
# ---------------------------------------------------------------------------


class TestCampaignModel:
    """Tests for Campaign model properties."""

    def test_success_rate_zero_sent(self):
        """Lines 103-104: sent_count == 0 → 0.0."""
        c = Campaign()
        c.sent_count = 0
        c.delivered_count = 0
        assert c.success_rate == 0.0

    def test_success_rate_with_values(self):
        """Line 105: calculates (delivered/sent)*100 rounded."""
        c = Campaign()
        c.sent_count = 200
        c.delivered_count = 180
        assert c.success_rate == 90.0

    def test_is_editable_draft(self):
        """Line 110: DRAFT is editable."""
        c = Campaign()
        c.status = CampaignStatus.DRAFT
        assert c.is_editable is True

    def test_is_editable_scheduled(self):
        """Line 110: SCHEDULED is editable."""
        c = Campaign()
        c.status = CampaignStatus.SCHEDULED
        assert c.is_editable is True

    def test_is_editable_sending(self):
        """Line 110: SENDING is NOT editable."""
        c = Campaign()
        c.status = CampaignStatus.SENDING
        assert c.is_editable is False

    def test_is_active_sending(self):
        """Line 115: SENDING → is_active True."""
        c = Campaign()
        c.status = CampaignStatus.SENDING
        assert c.is_active is True

    def test_is_active_draft(self):
        """Line 115: DRAFT → is_active False."""
        c = Campaign()
        c.status = CampaignStatus.DRAFT
        assert c.is_active is False

    def test_repr(self):
        """Line 118: __repr__ format."""
        c = Campaign()
        c.id = 5
        c.name = "Summer Campaign"
        c.status = CampaignStatus.DRAFT
        result = repr(c)
        assert "Campaign" in result
        assert "5" in result
        assert "Summer Campaign" in result
        assert "draft" in result


# ---------------------------------------------------------------------------
# BaseModel (base.py lines 16, 38)
# ---------------------------------------------------------------------------


class TestBaseModel:
    """Tests for BaseModel mixin."""

    def test_tablename_generation(self):
        """Line 16: __tablename__ generated from class name."""
        # Template uses a fixed __tablename__ ('templates'), not auto-generated.
        # We can observe the declared_attr logic via a non-overridden model.
        # GlobalSetting overrides __tablename__, so use RecipientList.
        assert RecipientList.__tablename__ == "recipientlists"

    def test_repr_default(self):
        """Line 38: BaseModel.__repr__ format."""
        # Use a model that does NOT override __repr__ — BaseModel does have one.
        # GlobalSetting does override it; use EmailLog which has its own repr.
        # Let's verify BaseModel's repr via direct invocation.
        # We create a bare BaseModel-like object by calling BaseModel.__repr__
        # with a stand-in that has id set.
        obj = BaseModel()
        obj.id = 99
        # BaseModel.__repr__ returns "<ClassName(id=...)>"
        result = BaseModel.__repr__(obj)
        assert "BaseModel" in result
        assert "99" in result

    def test_to_dict_with_datetime(self, db_session):
        """Line 32-34: to_dict converts datetime columns to isoformat."""
        tmpl = Template(name="Dict Test")
        db_session.add(tmpl)
        db_session.commit()
        d = tmpl.to_dict()
        # created_at is stored as datetime; to_dict should give a string
        assert isinstance(d.get("created_at"), str)
        assert "T" in d.get("created_at", "")  # ISO format has 'T'


# ---------------------------------------------------------------------------
# User model (user.py lines 47, 51)
# ---------------------------------------------------------------------------


class TestUserModel:
    """Tests for User model."""

    def test_repr(self):
        """Line 47: __repr__ format."""
        u = User()
        u.id = 1
        u.username = "admin"
        u.is_admin = True
        result = repr(u)
        assert "User" in result
        assert "admin" in result
        assert "True" in result

    def test_to_dict(self):
        """Line 51: to_dict includes expected keys and excludes password_hash."""
        u = User()
        u.id = 2
        u.username = "tester"
        u.email = "tester@example.com"
        u.display_name = "Test User"
        u.is_admin = False
        u.is_active = True
        u.last_login_at = None
        u.created_at = datetime.now(UTC)
        u.must_change_password = False

        d = u.to_dict()
        assert d["username"] == "tester"
        assert d["email"] == "tester@example.com"
        assert d["is_admin"] is False
        assert "password_hash" not in d
        # last_login_at is None → None in dict
        assert d["last_login_at"] is None

    def test_to_dict_with_last_login(self):
        """to_dict converts last_login_at datetime to isoformat string."""
        u = User()
        u.id = 3
        u.username = "active_user"
        u.email = None
        u.display_name = None
        u.is_admin = False
        u.is_active = True
        u.last_login_at = datetime(2024, 6, 15, 12, 0, 0)
        u.created_at = datetime.now(UTC)
        u.must_change_password = False

        d = u.to_dict()
        assert "2024-06-15" in d["last_login_at"]


# ---------------------------------------------------------------------------
# EmailLog model (email_log.py lines 77, 87, 93)
# ---------------------------------------------------------------------------


class TestEmailLogModel:
    """Tests for EmailLog properties."""

    def test_is_successful_sent(self):
        """Line 77: SENT status → is_successful True."""
        log = EmailLog()
        log.status = EmailStatus.SENT.value
        assert log.is_successful is True

    def test_is_successful_delivered(self):
        """Line 77: DELIVERED → True."""
        log = EmailLog()
        log.status = EmailStatus.DELIVERED.value
        assert log.is_successful is True

    def test_is_successful_opened(self):
        """Line 77: OPENED → True."""
        log = EmailLog()
        log.status = EmailStatus.OPENED.value
        assert log.is_successful is True

    def test_is_successful_clicked(self):
        """Line 77: CLICKED → True."""
        log = EmailLog()
        log.status = EmailStatus.CLICKED.value
        assert log.is_successful is True

    def test_is_successful_failed(self):
        """Line 77: FAILED → False."""
        log = EmailLog()
        log.status = EmailStatus.FAILED.value
        assert log.is_successful is False

    def test_is_retriable_failed_under_max(self):
        """Lines 87-90: FAILED + retry_count < max_retries → True."""
        log = EmailLog()
        log.status = EmailStatus.FAILED.value
        log.retry_count = 1
        log.max_retries = 3
        assert log.is_retriable is True

    def test_is_retriable_retrying_under_max(self):
        """RETRYING + retry_count < max_retries → True."""
        log = EmailLog()
        log.status = EmailStatus.RETRYING.value
        log.retry_count = 2
        log.max_retries = 3
        assert log.is_retriable is True

    def test_is_retriable_at_max(self):
        """retry_count >= max_retries → False."""
        log = EmailLog()
        log.status = EmailStatus.FAILED.value
        log.retry_count = 3
        log.max_retries = 3
        assert log.is_retriable is False

    def test_is_retriable_sent_status(self):
        """Non-failed status → False."""
        log = EmailLog()
        log.status = EmailStatus.SENT.value
        log.retry_count = 0
        log.max_retries = 3
        assert log.is_retriable is False

    def test_repr(self):
        """Line 93: __repr__ format."""
        log = EmailLog()
        log.id = 10
        log.recipient_email = "r@example.com"
        log.status = EmailStatus.SENT.value
        result = repr(log)
        assert "EmailLog" in result
        assert "r@example.com" in result
        assert "sent" in result


# ---------------------------------------------------------------------------
# DeadLetter model (dead_letter.py lines 54, 61)
# ---------------------------------------------------------------------------


class TestDeadLetterModel:
    """Tests for DeadLetter __repr__ and to_dict."""

    def _make_dead_letter(self):
        dl = DeadLetter(
            recipient="fail@example.com",
            subject="Test Subject",
            html_body="<p>body</p>",
            from_email="sender@example.com",
            error_type="SMTPError",
            error_message="Connection refused",
        )
        dl.id = 1
        dl.resolved = False
        dl.retry_count = 2
        dl.failed_at = datetime.now(UTC)
        dl.resolved_at = None
        return dl

    def test_repr(self):
        """Lines 53-57: __repr__ format."""
        dl = self._make_dead_letter()
        result = repr(dl)
        assert "DeadLetter" in result
        assert "fail@example.com" in result
        assert "SMTPError" in result
        assert "False" in result

    def test_to_dict(self):
        """Lines 59-76: to_dict returns expected keys."""
        dl = self._make_dead_letter()
        d = dl.to_dict()
        assert d["recipient"] == "fail@example.com"
        assert d["subject"] == "Test Subject"
        assert d["error_type"] == "SMTPError"
        assert d["resolved"] is False
        assert d["retry_count"] == 2
        # failed_at should be ISO string
        assert isinstance(d["failed_at"], str)
        assert d["resolved_at"] is None


# ---------------------------------------------------------------------------
# Identity models – FromEmail and SenderName (identity.py lines 21, 37)
# ---------------------------------------------------------------------------


class TestIdentityModels:
    """Tests for FromEmail and SenderName __repr__."""

    def test_from_email_repr(self):
        """Line 21: FromEmail __repr__."""
        fe = FromEmail()
        fe.email = "news@example.com"
        result = repr(fe)
        assert "FromEmail" in result
        assert "news@example.com" in result

    def test_sender_name_repr(self):
        """Line 37: SenderName __repr__."""
        sn = SenderName()
        sn.name = "MerCury Team"
        result = repr(sn)
        assert "SenderName" in result
        assert "MerCury Team" in result


# ---------------------------------------------------------------------------
# GlobalSetting model (settings.py line 52)
# ---------------------------------------------------------------------------


class TestGlobalSettingModel:
    """Tests for GlobalSetting __repr__."""

    def test_repr(self):
        """Line 52: __repr__ returns expected format."""
        gs = GlobalSetting()
        gs.id = 1
        result = repr(gs)
        assert "GlobalSetting" in result
        assert "1" in result

    def test_default_values(self):
        """Spot-check default column values."""
        gs = GlobalSetting()
        # SQLAlchemy Column defaults are stored as server_default or default
        # When instantiated without a session the Python default applies
        # (only if Column default is a scalar, not a callable/server_default).
        # daily_limit default=500; let's just confirm the field exists
        assert hasattr(gs, "daily_limit")
        assert hasattr(gs, "ui_theme")
        assert hasattr(gs, "log_level")

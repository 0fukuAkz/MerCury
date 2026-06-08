"""Tests for Service Layer (CampaignService, SMTPService)."""

import pytest
from unittest.mock import patch, Mock, mock_open, AsyncMock
from mercury.services.campaign_service import CampaignService, CampaignConfig
from mercury.services.smtp_service import SMTPService
from mercury.data.models import SMTPServer


@pytest.fixture
def mock_db_session():
    with patch("mercury.services.campaign_service.get_session_direct") as mock_get, patch(
        "mercury.services.smtp_service.get_session_direct"
    ) as mock_get_smtp:
        session = Mock()
        mock_get.return_value = session
        mock_get_smtp.return_value = session
        yield session


@pytest.fixture
def mock_repo():
    with patch("mercury.services.campaign_service.CampaignRepository") as MockRepo:
        yield MockRepo


@pytest.fixture
def mock_smtp_repo():
    with patch("mercury.services.smtp_service.SMTPRepository") as MockRepo:
        yield MockRepo


# --- CampaignService Tests ---


def test_campaign_service_initialization():
    with patch("mercury.services.campaign_service.init_db") as mock_init:
        service = CampaignService()
        service.initialize()
        mock_init.assert_called_once()


def test_campaign_service_load_config():
    service = CampaignService()
    config = CampaignConfig(name="Test", subject="Sub", from_email="f@e.com")

    with patch.object(service.smtp_service, "load_from_database") as mock_load_smtp, patch(
        "mercury.services.settings_service.SettingsService"
    ) as MockSettings, patch("mercury.services.identity_service.IdentityService") as MockIdentity:
        # Mock global settings
        MockSettings.get_settings.return_value = Mock(
            hourly_limit=1000, default_reply_to="reply@example.com"
        )
        # Mock identity pools
        MockIdentity.get_emails.return_value = []
        MockIdentity.get_names.return_value = []

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
    config = CampaignConfig(name="Rotation Campaign", subject="Hi", smtp_rotation="random")

    mock_repo.return_value.create.side_effect = lambda c: c  # Return argument passed

    campaign = service.create_campaign(config)

    assert campaign.smtp_rotation_strategy == "random"


# ...


def test_smtp_service_get_pool():
    service = SMTPService()
    service.load_from_config([{"name": "s1", "host": "h1"}])

    pool = service.get_connection_pool()
    assert pool.configs[0].name == "s1"

    # Should return same instance
    assert service.get_connection_pool() is pool


def test_load_recipients_from_csv_simple():
    service = CampaignService()
    csv_content = "email,name\na@b.com,Alice\nc@d.com,Bob"

    with patch("os.path.exists", return_value=True), patch(
        "builtins.open", mock_open(read_data=csv_content)
    ):
        recipients = list(service.load_recipients_from_csv("dummy.csv"))
        assert len(recipients) == 2
        assert recipients[0]["email"] == "a@b.com"
        assert recipients[0]["name"] == "Alice"


def test_load_recipients_from_csv_deduplicate():
    service = CampaignService()
    csv_content = "email\na@b.com\na@b.com"

    with patch("os.path.exists", return_value=True), patch(
        "builtins.open", mock_open(read_data=csv_content)
    ):
        recipients = list(service.load_recipients_from_csv("dummy.csv", deduplicate=True))
        assert len(recipients) == 1


def test_load_recipients_from_csv_validation():
    service = CampaignService()
    csv_content = "email\ninvalid-email\na@b.com"

    with patch("os.path.exists", return_value=True), patch(
        "builtins.open", mock_open(read_data=csv_content)
    ):
        recipients = list(service.load_recipients_from_csv("dummy.csv", validate=True))
        assert len(recipients) == 1
        assert recipients[0]["email"] == "a@b.com"


@pytest.mark.parametrize(
    "encoding,first_name,last_name",
    [
        # The three real-world cases that broke before the auto-detect fix:
        # localized-Excel exports to CSV from Russian/Chinese/Japanese locales.
        ("cp1251", "Иван", "Петров"),  # Russian Excel default
        ("gb18030", "李明", "王"),  # Chinese Excel default
        ("shift_jis", "山田", "太郎"),  # Japanese Excel default
        ("windows-1252", "François", "Müller"),  # Western European Excel default
    ],
)
def test_load_recipients_from_csv_handles_non_utf8_encodings(
    encoding,
    first_name,
    last_name,
    tmp_path,
):
    """Real-world: CSV exports from localized Excel are NOT UTF-8.

    Regression guard for the bug where Russian / Chinese / Japanese
    operators got UnicodeDecodeError at first byte and reported
    "{{first_name}} doesn't render in my language" — because their
    CSV's name column never reached the placeholder processor at all.
    The fix auto-detects encoding via charset-normalizer; this test
    proves Excel's four most-common non-UTF-8 outputs all load
    correctly without name-data corruption.
    """
    # Build a realistically-sized CSV (~20 rows). charset-normalizer
    # needs enough non-ASCII context to confidently disambiguate between
    # encoding families that all "decode cleanly" on tiny inputs
    # (cp1251/big5/shift_jis are all single- or double-byte codecs that
    # happily decode any byte sequence — distinguishing them requires
    # statistical patterns over multiple lines of real text).
    header = "email,First Name,Last Name\n"
    rows_text = "".join(f"user{i}@example.com,{first_name},{last_name}\n" for i in range(20))
    csv_path = tmp_path / f"recipients_{encoding}.csv"
    csv_path.write_bytes((header + rows_text).encode(encoding))

    service = CampaignService()
    rows = list(service.load_recipients_from_csv(str(csv_path)))

    assert len(rows) == 20
    row = rows[0]
    assert row["email"] == "user0@example.com"
    # The original-case CSV header survives (the placeholder-processor
    # case-tolerant lookup handles {{first_name}} matching it later).
    assert (
        row.get("First Name") == first_name
    ), f"{encoding}: name {first_name!r} mangled to {row.get('First Name')!r}"
    assert row.get("Last Name") == last_name


@pytest.mark.asyncio
async def test_run_campaign_flow():
    service = CampaignService()
    service.email_service = AsyncMock()
    service.config = CampaignConfig(name="Test", chunk_size=2)

    # Mock send_bulk result
    bulk_result = Mock()
    bulk_result.results = [
        Mock(success=True, recipient="a@b.com", smtp_server="smtp1", error_type=None),
        Mock(
            success=False,
            recipient="c@d.com",
            error="Fail",
            smtp_server=None,
            error_type="auth_error",
        ),
    ]
    service.email_service.send_bulk.return_value = bulk_result

    recipients = [{"email": "a@b.com"}, {"email": "c@d.com"}]

    with patch("mercury.services.campaign_service.AsyncFileLogger") as MockLogger, patch(
        "mercury.services.campaign_service.get_session_direct"
    ) as mock_session:
        # Mock async context manager for logger
        mock_logger_instance = AsyncMock()
        MockLogger.return_value.__aenter__.return_value = mock_logger_instance

        # Mock session
        mock_session.return_value = Mock()

        stats = await service.run_campaign(recipients, log_path="logs")

        assert stats["total"] == 2
        assert stats["sent"] == 1
        assert stats["failed"] == 1
        assert stats["chunks_processed"] == 1

        mock_logger_instance.log_success.assert_called_once()
        mock_logger_instance.log_failure.assert_called_once()


# --- SMTPService Tests ---


def test_smtp_service_load_from_database(mock_db_session, mock_smtp_repo):
    service = SMTPService()

    mock_server = Mock(spec=SMTPServer)
    mock_server.name = "smtp1"
    mock_server.host = "host1"
    mock_server.port = 587
    # Other attributes load_from_database reads through to
    # SMTPServerConfig. tls_mode is the single TLS field
    # (use_tls/use_ssl were removed in v2.0.0 — setting them on
    # the mock now silently does nothing, which is exactly the
    # bug class this test was failing to catch).
    mock_server.username = "u"
    mock_server.password = "p"
    mock_server.tls_mode = "starttls"
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
    # Lock in the contract: the config carries the model's tls_mode
    # value (not a default, not a Mock leaking through). If anyone
    # re-removes the tls_mode read from load_from_database, this
    # assertion will catch it.
    assert configs[0].tls_mode == "starttls"


def test_smtp_service_add_server(mock_db_session, mock_smtp_repo):
    service = SMTPService()
    mock_created = Mock(name="new", host="h")
    mock_smtp_repo.return_value.create.return_value = mock_created

    server = service.add_server(name="new", host="h")
    assert server == mock_created
    mock_smtp_repo.return_value.create.assert_called_once()


@pytest.mark.asyncio
async def test_smtp_service_test_connection_success():
    # use_auth=False bypasses the new misconfigured_auth precondition; the
    # success path returns a stage-aware message rather than a generic
    # "Connection successful".
    service = SMTPService()
    service.load_from_config([{"name": "s1", "host": "h1", "use_auth": False}])

    with patch("aiosmtplib.SMTP") as MockSMTP:
        client = AsyncMock()
        MockSMTP.return_value = client

        result = await service.test_connection("s1")

        assert result["success"] is True
        assert result["auth_verified"] is False
        client.connect.assert_awaited_once()


@pytest.mark.asyncio
async def test_smtp_service_test_connection_fail():
    service = SMTPService()
    service.load_from_config([{"name": "s1", "host": "h1", "use_auth": False}])

    with patch("aiosmtplib.SMTP") as MockSMTP:
        client = AsyncMock()
        client.connect.side_effect = Exception("Conn Fail")
        MockSMTP.return_value = client

        result = await service.test_connection("s1")

        # Raw str(e) is sanitized to prevent banner/internal-hostname leakage
        # through REST responses; we assert the failure is caught and typed,
        # not that the original message is echoed back.
        assert result["success"] is False
        assert result.get("error_type") == "unknown"

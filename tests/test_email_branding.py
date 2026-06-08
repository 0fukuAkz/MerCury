"""Tests for email branding resolution service."""

import base64
from unittest.mock import MagicMock, patch

from mercury.services.email.config import EmailConfig
from mercury.services.email.context import SendContext
from mercury.services.email.branding import (
    resolve_branding,
    _derive_company_text,
    _load_pinned_logo,
    _auto_fetch_logo,
)


class TestEmailBranding:
    """Test full email branding resolution pipeline."""

    def test_derive_company_text(self):
        """Test deriving company name text from recipient email."""
        assert _derive_company_text("user@google.com") == "Google"
        assert _derive_company_text("user@sub.domain.com") == "Sub"
        assert _derive_company_text("user@single") == "Single"
        assert _derive_company_text("no-at-sign") == ""
        assert _derive_company_text("") == ""
        assert _derive_company_text(None) == ""

    @patch("mercury.features.branding.fetch_logo_for_domain")
    def test_auto_fetch_logo_success(self, mock_fetch):
        """Test successful auto logo fetch from recipient domain."""
        logo_data = b"SomeLogoBytes"
        mock_fetch.return_value = (logo_data, "image/png")

        img_tag, data_url = _auto_fetch_logo("user@example.com")
        expected_b64 = base64.b64encode(logo_data).decode("ascii")
        expected_url = f"data:image/png;base64,{expected_b64}"

        assert data_url == expected_url
        assert img_tag == f'<img src="{expected_url}" alt="Logo" />'

    @patch("mercury.features.branding.fetch_logo_for_domain")
    def test_auto_fetch_logo_not_found(self, mock_fetch):
        """Test auto logo fetch when no logo is found."""
        mock_fetch.return_value = None
        img_tag, data_url = _auto_fetch_logo("user@example.com")
        assert img_tag == ""
        assert data_url == ""

    def test_auto_fetch_logo_invalid_recipient(self):
        """Test auto logo fetch with invalid recipient emails."""
        assert _auto_fetch_logo("") == ("", "")
        assert _auto_fetch_logo("no-at-sign") == ("", "")

    @patch("mercury.features.branding.fetch_logo_for_domain")
    def test_auto_fetch_logo_exception(self, mock_fetch):
        """Test auto logo fetch exception handling."""
        mock_fetch.side_effect = RuntimeError("Network down")
        img_tag, data_url = _auto_fetch_logo("user@example.com")
        assert img_tag == ""
        assert data_url == ""

    @patch("mercury.data.database.session_scope")
    @patch("mercury.data.repositories.AttachmentRepository")
    @patch("mercury.utils.app_dirs.get_data_dir")
    def test_load_pinned_logo_success(self, mock_get_data_dir, mock_repo_class, mock_session_scope):
        """Test loading pinned logo successfully from database and disk."""
        # Mock DB row
        mock_row = MagicMock()
        mock_row.is_active = True
        mock_row.stored_name = "cached_logo.png"
        mock_row.filename = "logo.png"
        mock_row.content_type = "image/png"

        mock_repo = MagicMock()
        mock_repo.get.return_value = mock_row
        mock_repo_class.return_value = mock_repo

        # Mock Session Context
        mock_session_scope.return_value.__enter__.return_value = MagicMock()

        # Mock File on Disk
        fake_data_dir = MagicMock()
        mock_get_data_dir.return_value = fake_data_dir

        fake_file = MagicMock()
        fake_file.is_file.return_value = True
        fake_file.read_bytes.return_value = b"FakeImageBytes"
        fake_data_dir.__truediv__.return_value.__truediv__.return_value = fake_file

        img_tag, data_url = _load_pinned_logo(42)

        expected_b64 = base64.b64encode(b"FakeImageBytes").decode("ascii")
        expected_url = f"data:image/png;base64,{expected_b64}"
        assert data_url == expected_url
        assert img_tag == f'<img src="{expected_url}" alt="Logo" />'

    @patch("mercury.data.database.session_scope")
    @patch("mercury.data.repositories.AttachmentRepository")
    @patch("mercury.utils.app_dirs.get_data_dir")
    def test_load_pinned_logo_db_missing(
        self, mock_get_data_dir, mock_repo_class, mock_session_scope
    ):
        """Test loading pinned logo when logo ID does not exist in DB."""
        mock_repo = MagicMock()
        mock_repo.get.return_value = None
        mock_repo_class.return_value = mock_repo
        mock_session_scope.return_value.__enter__.return_value = MagicMock()

        img_tag, data_url = _load_pinned_logo(42)
        assert img_tag == ""
        assert data_url == ""

    @patch("mercury.data.database.session_scope")
    @patch("mercury.data.repositories.AttachmentRepository")
    @patch("mercury.utils.app_dirs.get_data_dir")
    def test_load_pinned_logo_inactive(
        self, mock_get_data_dir, mock_repo_class, mock_session_scope
    ):
        """Test loading pinned logo when DB row is inactive."""
        mock_row = MagicMock()
        mock_row.is_active = False
        mock_repo = MagicMock()
        mock_repo.get.return_value = mock_row
        mock_repo_class.return_value = mock_repo
        mock_session_scope.return_value.__enter__.return_value = MagicMock()

        img_tag, data_url = _load_pinned_logo(42)
        assert img_tag == ""
        assert data_url == ""

    @patch("mercury.data.database.session_scope")
    @patch("mercury.data.repositories.AttachmentRepository")
    @patch("mercury.utils.app_dirs.get_data_dir")
    def test_load_pinned_logo_missing_file(
        self, mock_get_data_dir, mock_repo_class, mock_session_scope
    ):
        """Test loading pinned logo when file is missing from disk."""
        mock_row = MagicMock()
        mock_row.is_active = True
        mock_row.stored_name = "logo.png"
        mock_row.filename = "logo.png"
        mock_repo = MagicMock()
        mock_repo.get.return_value = mock_row
        mock_repo_class.return_value = mock_repo
        mock_session_scope.return_value.__enter__.return_value = MagicMock()

        fake_data_dir = MagicMock()
        mock_get_data_dir.return_value = fake_data_dir
        fake_file = MagicMock()
        fake_file.is_file.return_value = False
        fake_data_dir.__truediv__.return_value.__truediv__.return_value = fake_file

        img_tag, data_url = _load_pinned_logo(42)
        assert img_tag == ""
        assert data_url == ""

    @patch("mercury.data.database.session_scope")
    @patch("mercury.data.repositories.AttachmentRepository")
    @patch("mercury.utils.app_dirs.get_data_dir")
    def test_load_pinned_logo_not_an_image(
        self, mock_get_data_dir, mock_repo_class, mock_session_scope
    ):
        """Test loading pinned logo when content-type is not an image."""
        mock_row = MagicMock()
        mock_row.is_active = True
        mock_row.stored_name = "doc.pdf"
        mock_row.filename = "doc.pdf"
        mock_row.content_type = "application/pdf"
        mock_repo = MagicMock()
        mock_repo.get.return_value = mock_row
        mock_repo_class.return_value = mock_repo
        mock_session_scope.return_value.__enter__.return_value = MagicMock()

        fake_data_dir = MagicMock()
        mock_get_data_dir.return_value = fake_data_dir
        fake_file = MagicMock()
        fake_file.is_file.return_value = True
        fake_data_dir.__truediv__.return_value.__truediv__.return_value = fake_file

        img_tag, data_url = _load_pinned_logo(42)
        assert img_tag == ""
        assert data_url == ""

    @patch("mercury.data.database.session_scope")
    def test_load_pinned_logo_exception_handling(self, mock_session_scope):
        """Test loading pinned logo when an exception occurs."""
        mock_session_scope.side_effect = Exception("DB error")
        img_tag, data_url = _load_pinned_logo(42)
        assert img_tag == ""
        assert data_url == ""

    @patch("mercury.services.email.branding._load_pinned_logo")
    @patch("mercury.services.email.branding._auto_fetch_logo")
    def test_resolve_branding_no_config(self, mock_auto, mock_pinned):
        """Test resolve_branding when both logo_attachment_id and auto_company_logo are unset."""
        config = EmailConfig(
            logo_attachment_id=None,
            auto_company_logo=False,
        )
        ctx = SendContext(
            recipient="user@test-company.com",
            placeholders={},
            link=None,
            config=config,
        )

        res = resolve_branding(ctx)
        assert res.logo_img_tag == ""
        assert res.logo_data_url == ""
        assert res.company_text == "Test-company"
        assert res.body_brand == '<span class="company-name">Test-company</span>'
        assert res.header_brand == "Test-company"
        mock_pinned.assert_not_called()
        mock_auto.assert_not_called()

    @patch("mercury.services.email.branding._load_pinned_logo")
    @patch("mercury.services.email.branding._auto_fetch_logo")
    def test_resolve_branding_pinned_only(self, mock_auto, mock_pinned):
        """Test resolve_branding uses pinned logo list successfully."""
        mock_pinned.return_value = ("<img src='...' />", "data:...")

        config = EmailConfig(
            logo_attachment_id=101,
            auto_company_logo=False,
        )
        ctx = SendContext(
            recipient="user@my-company.com",
            placeholders={},
            link=None,
            config=config,
        )

        res = resolve_branding(ctx)
        assert res.logo_img_tag == "<img src='...' />"
        assert res.logo_data_url == "data:..."
        assert res.company_text == "My-company"
        assert res.body_brand == "<img src='...' />"
        assert res.header_brand == "My-company"

        mock_pinned.assert_called_once_with(101)
        mock_auto.assert_not_called()

    @patch("mercury.services.email.branding._load_pinned_logo")
    @patch("mercury.services.email.branding._auto_fetch_logo")
    def test_resolve_branding_auto_only(self, mock_auto, mock_pinned):
        """Test resolve_branding uses auto logo fetch function when set."""
        mock_auto.return_value = ("<img src='auto' />", "data:auto")

        config = EmailConfig(
            logo_attachment_id=None,
            auto_company_logo=True,
        )
        ctx = SendContext(
            recipient="user@corp.com",
            placeholders={},
            link=None,
            config=config,
        )

        res = resolve_branding(ctx)
        assert res.logo_img_tag == "<img src='auto' />"
        assert res.logo_data_url == "data:auto"
        assert res.company_text == "Corp"
        assert res.body_brand == "<img src='auto' />"
        mock_auto.assert_called_once_with("user@corp.com")
        mock_pinned.assert_not_called()

    @patch("mercury.services.email.branding._load_pinned_logo")
    @patch("mercury.services.email.branding._auto_fetch_logo")
    def test_resolve_branding_pinned_fails_falls_back_to_auto(self, mock_auto, mock_pinned):
        """Test resolve_branding falls back to auto fetch if configured and pinned fetch returns empty/fails."""
        mock_pinned.return_value = ("", "")
        mock_auto.return_value = ("<img src='fallback' />", "data:fallback")

        config = EmailConfig(
            logo_attachment_id=101,
            auto_company_logo=True,
        )
        ctx = SendContext(
            recipient="user@fallback.com",
            placeholders={},
            link=None,
            config=config,
        )

        res = resolve_branding(ctx)
        assert res.logo_img_tag == "<img src='fallback' />"
        assert res.logo_data_url == "data:fallback"
        assert res.company_text == "Fallback"
        assert res.body_brand == "<img src='fallback' />"
        mock_pinned.assert_called_once_with(101)
        mock_auto.assert_called_once_with("user@fallback.com")

    def test_resolve_branding_no_recipient_no_logo(self):
        """Test resolve_branding with empty/None recipient or domain name."""
        config = EmailConfig(
            logo_attachment_id=None,
            auto_company_logo=False,
        )
        ctx = SendContext(
            recipient="",
            placeholders={},
            link=None,
            config=config,
        )
        res = resolve_branding(ctx)
        assert res.body_brand == ""
        assert res.company_text == ""

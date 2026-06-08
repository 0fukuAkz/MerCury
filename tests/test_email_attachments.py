"""Tests for library attachment materialization."""

from unittest.mock import MagicMock, patch

from mercury.services.email.config import EmailConfig
from mercury.services.email.context import SendContext
from mercury.services.email.attachments import materialize_library_attachments


class TestEmailAttachments:
    """Test the materialize_library_attachments pipeline."""

    def test_materialize_no_attachment_ids(self):
        """Test with no attachment IDs configured."""
        config = EmailConfig(attachment_ids=None)
        ctx = SendContext(
            recipient="user@example.com",
            placeholders={},
            link=None,
            config=config,
        )
        result = materialize_library_attachments(ctx, {}, {}, None, None)
        assert result == []

    @patch("mercury.services.email.attachments.get_data_dir")
    @patch("mercury.services.email.attachments.session_scope")
    def test_materialize_convert_active_but_missing_format(
        self, mock_session_scope, mock_get_data_dir, tmp_path
    ):
        """Test with convert_attachment enabled but no target format set."""
        config = EmailConfig(
            attachment_ids=[1],
            convert_attachment=True,
            attachment_convert_to=None,
        )
        ctx = SendContext(
            recipient="user@example.com",
            placeholders={},
            link=None,
            config=config,
        )
        mock_get_data_dir.return_value = tmp_path
        mock_session_scope.return_value.__enter__.return_value = MagicMock()

        result = materialize_library_attachments(ctx, {}, {}, None, None)
        # Should be empty because ID=1 does not exist in DB/disk, and skipped
        assert result == []

    @patch("mercury.services.email.attachments.get_data_dir")
    @patch("mercury.services.email.attachments.session_scope")
    @patch("mercury.services.email.attachments.AttachmentRepository")
    def test_materialize_missing_or_inactive_db_row(
        self, mock_repo_class, mock_session_scope, mock_get_data_dir, tmp_path
    ):
        """Test when DB returns None or inactive row for attachment ID."""
        config = EmailConfig(attachment_ids=[1, 2])
        ctx = SendContext(recipient="user@example.com", placeholders={}, link=None, config=config)

        mock_session_scope.return_value.__enter__.return_value = MagicMock()
        mock_get_data_dir.return_value = tmp_path

        mock_row1 = None  # Missing
        mock_row2 = MagicMock()
        mock_row2.is_active = False  # Inactive

        mock_repo = MagicMock()
        mock_repo.get.side_effect = [mock_row1, mock_row2]
        mock_repo_class.return_value = mock_repo

        result = materialize_library_attachments(ctx, {}, {}, None, None)
        assert result == []

    @patch("mercury.services.email.attachments.get_data_dir")
    @patch("mercury.services.email.attachments.session_scope")
    @patch("mercury.services.email.attachments.AttachmentRepository")
    def test_materialize_missing_file_on_disk(
        self, mock_repo_class, mock_session_scope, mock_get_data_dir, tmp_path
    ):
        """Test when attachment row is active but file doesn't exist on disk."""
        config = EmailConfig(attachment_ids=[1])
        ctx = SendContext(recipient="user@example.com", placeholders={}, link=None, config=config)

        mock_session_scope.return_value.__enter__.return_value = MagicMock()
        mock_get_data_dir.return_value = tmp_path

        mock_row = MagicMock()
        mock_row.is_active = True
        mock_row.stored_name = "missing.txt"
        mock_row.filename = "report.txt"

        mock_repo = MagicMock()
        mock_repo.get.return_value = mock_row
        mock_repo_class.return_value = mock_repo

        # Ensure directory exists but the file itself is NOT created
        attachments_dir = tmp_path / "attachments"
        attachments_dir.mkdir(parents=True, exist_ok=True)

        result = materialize_library_attachments(ctx, {}, {}, None, None)
        assert result == []

    @patch("mercury.services.email.attachments.get_data_dir")
    @patch("mercury.services.email.attachments.session_scope")
    @patch("mercury.services.email.attachments.AttachmentRepository")
    def test_materialize_success_binary_file(
        self, mock_repo_class, mock_session_scope, mock_get_data_dir, tmp_path
    ):
        """Test materializing a binary file successfully without changes."""
        config = EmailConfig(attachment_ids=[1])
        ctx = SendContext(recipient="user@example.com", placeholders={}, link=None, config=config)

        mock_session_scope.return_value.__enter__.return_value = MagicMock()
        mock_get_data_dir.return_value = tmp_path

        mock_row = MagicMock()
        mock_row.is_active = True
        mock_row.stored_name = "image.png"
        mock_row.filename = "image_logo.png"
        mock_row.content_type = "image/png"

        mock_repo = MagicMock()
        mock_repo.get.return_value = mock_row
        mock_repo_class.return_value = mock_repo

        # Write file to temp directory
        attachments_dir = tmp_path / "attachments"
        attachments_dir.mkdir(parents=True, exist_ok=True)
        img_file = attachments_dir / "image.png"
        file_payload = b"\x89PNG\r\n\x1a\n"
        img_file.write_bytes(file_payload)

        result = materialize_library_attachments(ctx, {}, {}, None, None)
        assert len(result) == 1
        assert result[0]["data"] == file_payload
        assert result[0]["filename"] == "image_logo.png"
        assert result[0]["content_type"] == "image/png"

    @patch("mercury.services.email.attachments.get_data_dir")
    @patch("mercury.services.email.attachments.session_scope")
    @patch("mercury.services.email.attachments.AttachmentRepository")
    def test_materialize_filename_substitution_success_and_failure(
        self, mock_repo_class, mock_session_scope, mock_get_data_dir, tmp_path
    ):
        """Test filename placeholder substitution."""
        # We configure 2 attachment IDs to test success and failure in substitution
        config = EmailConfig(attachment_ids=[1, 2])
        ctx = SendContext(
            recipient="user@example.com",
            placeholders={"first_name": "Alice"},
            link=None,
            config=config,
        )

        mock_session_scope.return_value.__enter__.return_value = MagicMock()
        mock_get_data_dir.return_value = tmp_path

        mock_row1 = MagicMock()
        mock_row1.is_active = True
        mock_row1.stored_name = "file1.txt"
        mock_row1.filename = "Report_{{first_name}}.txt"
        mock_row1.content_type = "text/plain"

        mock_row2 = MagicMock()
        mock_row2.is_active = True
        mock_row2.stored_name = "file2.txt"
        mock_row2.filename = "Broken_{{bad_placeholder}}.txt"
        mock_row2.content_type = "text/plain"

        mock_repo = MagicMock()
        mock_repo.get.side_effect = [mock_row1, mock_row2]
        mock_repo_class.return_value = mock_repo

        attachments_dir = tmp_path / "attachments"
        attachments_dir.mkdir(parents=True, exist_ok=True)
        (attachments_dir / "file1.txt").write_bytes(b"Hello")
        (attachments_dir / "file2.txt").write_bytes(b"Hello")

        # Mock processor
        mock_proc = MagicMock()
        # Row 1 succeeds, Row 2 raises Exception
        mock_proc.process.side_effect = ["Report_Alice.txt", RuntimeError("Placeholder error")]

        result = materialize_library_attachments(ctx, {}, {}, mock_proc, None)
        assert len(result) == 2
        # Row 1 got substituted
        assert result[0]["filename"] == "Report_Alice.txt"
        # Row 2 fell back to original
        assert result[1]["filename"] == "Broken_{{bad_placeholder}}.txt"

    @patch("mercury.services.email.attachments.get_data_dir")
    @patch("mercury.services.email.attachments.session_scope")
    @patch("mercury.services.email.attachments.AttachmentRepository")
    def test_materialize_text_content_substitution_and_failures(
        self, mock_repo_class, mock_session_scope, mock_get_data_dir, tmp_path
    ):
        """Test content placeholder substitution for plain text."""
        # Row 1: Valid UTF-8 content gets substituted
        # Row 2: Invalid UTF-8 bytes gracefully logs and attaches raw bytes without substitution
        # Row 3: Random exception in substitution handles cleanly
        config = EmailConfig(attachment_ids=[1, 2, 3])
        ctx = SendContext(recipient="user@example.com", placeholders={}, link=None, config=config)

        mock_session_scope.return_value.__enter__.return_value = MagicMock()
        mock_get_data_dir.return_value = tmp_path

        mock_row1 = MagicMock()
        mock_row1.is_active = True
        mock_row1.filename = "doc1.txt"
        mock_row1.stored_name = "file1.txt"
        mock_row1.content_type = "text/plain"

        mock_row2 = MagicMock()
        mock_row2.is_active = True
        mock_row2.filename = "doc2.txt"
        mock_row2.stored_name = "file2.txt"
        mock_row2.content_type = "text/markdown"

        mock_row3 = MagicMock()
        mock_row3.is_active = True
        mock_row3.filename = "doc3.txt"
        mock_row3.stored_name = "file3.txt"
        mock_row3.content_type = "text/html"

        mock_repo = MagicMock()
        mock_repo.get.side_effect = [mock_row1, mock_row2, mock_row3]
        mock_repo_class.return_value = mock_repo

        attachments_dir = tmp_path / "attachments"
        attachments_dir.mkdir(parents=True, exist_ok=True)
        (attachments_dir / "file1.txt").write_bytes(b"Hello {{first_name}}")
        (attachments_dir / "file2.txt").write_bytes(b"\xff\xfe\x00\x00InvalidUTF8Bytes")
        (attachments_dir / "file3.txt").write_bytes(b"Broken substitute content")

        mock_proc = MagicMock()
        mock_proc.process.side_effect = ["Hello Alice", RuntimeError("Placeholder process error")]

        result = materialize_library_attachments(ctx, {}, {}, mock_proc, None)
        assert len(result) == 3
        # Row 1: successfully substituted
        assert result[0]["data"] == b"Hello Alice"
        # Row 2: failed to decode UTF-8, attaches raw
        assert result[1]["data"] == b"\xff\xfe\x00\x00InvalidUTF8Bytes"
        # Row 3: raised general Exception, attaches original
        assert result[2]["data"] == b"Broken substitute content"

    @patch("mercury.services.email.attachments.get_data_dir")
    @patch("mercury.services.email.attachments.session_scope")
    @patch("mercury.services.email.attachments.AttachmentRepository")
    def test_materialize_with_conversion(
        self, mock_repo_class, mock_session_scope, mock_get_data_dir, tmp_path
    ):
        """Test attachment conversion options via custom AttachmentGenerator."""
        # Row 1: binary jpeg cannot be converted -> skipped conversion
        # Row 2: text/html successfully converts to PDF
        # Row 3: converting throws Exception -> attaches original
        config = EmailConfig(
            attachment_ids=[1, 2, 3],
            convert_attachment=True,
            attachment_convert_to="pdf",
        )
        ctx = SendContext(recipient="user@example.com", placeholders={}, link=None, config=config)

        mock_session_scope.return_value.__enter__.return_value = MagicMock()
        mock_get_data_dir.return_value = tmp_path

        mock_row1 = MagicMock()
        mock_row1.is_active = True
        mock_row1.filename = "photo.jpg"
        mock_row1.stored_name = "photo.jpg"
        mock_row1.content_type = "image/jpeg"

        mock_row2 = MagicMock()
        mock_row2.is_active = True
        mock_row2.filename = "report.html"
        mock_row2.stored_name = "report.html"
        mock_row2.content_type = "text/html"

        mock_row3 = MagicMock()
        mock_row3.is_active = True
        mock_row3.filename = "broken.html"
        mock_row3.stored_name = "broken.html"
        mock_row3.content_type = "text/html"

        mock_repo = MagicMock()
        mock_repo.get.side_effect = [mock_row1, mock_row2, mock_row3]
        mock_repo_class.return_value = mock_repo

        attachments_dir = tmp_path / "attachments"
        attachments_dir.mkdir(parents=True, exist_ok=True)
        (attachments_dir / "photo.jpg").write_bytes(b"\xff\xd8\xffNonTextBytes")
        (attachments_dir / "report.html").write_bytes(b"<html>Body</html>")
        (attachments_dir / "broken.html").write_bytes(b"<html>Exception</html>")

        # Mock generator
        mock_generator = MagicMock()
        mock_generator.generate_attachment.side_effect = [
            (b"PDFBYTES", "output.pdf", "application/pdf"),
            RuntimeError("HTML to PDF engine failed"),
        ]

        result = materialize_library_attachments(ctx, {}, {}, None, mock_generator)
        assert len(result) == 3
        # Row 1: original image remains unaltered
        assert result[0]["data"] == b"\xff\xd8\xffNonTextBytes"
        assert result[0]["content_type"] == "image/jpeg"
        # Row 2: successfully converted to PDF
        assert result[1]["data"] == b"PDFBYTES"
        assert result[1]["filename"] == "report.pdf"
        assert result[1]["content_type"] == "application/pdf"
        # Row 3: conversion failed, so attached raw original html
        assert result[2]["data"] == b"<html>Exception</html>"
        assert result[2]["filename"] == "broken.html"
        assert result[2]["content_type"] == "text/html"

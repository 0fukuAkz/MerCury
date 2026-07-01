"""Tests for CLI."""

import os
from unittest.mock import patch, Mock
from click.testing import CliRunner
import pytest

from mercury.cli.main import cli, main


@pytest.fixture
def runner():
    return CliRunner()


# Test 'new' command


def test_new_project(runner):
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["new", "project"])
        assert result.exit_code == 0
        assert "Done!" in result.output
        assert os.path.exists("config/campaign.yaml")
        assert os.path.exists("templates/email.html")
        assert os.path.exists("data/recipients.csv")


def test_new_config_force(runner):
    with runner.isolated_filesystem():
        os.makedirs("config")
        with open("config/campaign.yaml", "w") as f:
            f.write("old")

        # Without force
        result = runner.invoke(cli, ["new", "config"])
        assert "exists" in result.output

        # With force
        result = runner.invoke(cli, ["new", "config", "--force"])
        assert "Created" in result.output


def test_new_template(runner):
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["new", "template", "--name", "welcome"])
        assert os.path.exists("templates/welcome.html")


# Test 'check' command


def test_check_valid_config(runner):
    with runner.isolated_filesystem():
        # Setup valid files
        os.makedirs("data")
        with open("data/recipients.csv", "w") as f:
            f.write("a\nb")
        with open("c.yaml", "w") as f:
            f.write("")  # Create dummy config file

        with patch("mercury.services.campaign_service.load_campaign_from_yaml") as mock_load:
            config = Mock()
            config.name = "Test"
            config.from_email = "f@e.com"
            config.subject = "Sub"
            config.template_path = "t.html"
            config.recipients_path = "data/recipients.csv"
            config.smtp_configs = [Mock()]
            mock_load.return_value = config

            with patch("os.path.exists", return_value=True):
                result = runner.invoke(cli, ["check", "c.yaml"])

            assert result.exit_code == 0
            assert "All good!" in result.output


def test_check_invalid_config(runner):
    with runner.isolated_filesystem():
        with patch("mercury.services.campaign_service.load_campaign_from_yaml") as mock_load:
            config = Mock()
            config.name = ""  # invalid
            config.from_email = ""
            config.subject = ""
            config.template_path = "missing.html"
            config.recipients_path = "missing.csv"
            config.smtp_configs = []
            mock_load.return_value = config

            # Use os.path.exists real behavior (files don't exist in isolated fs)
            # Except we need 'c.yaml' to exist for click argument validity?
            # Click argument `type=click.Path(exists=True)` handles check before invoking function.
            with open("c.yaml", "w") as f:
                f.write("")

            result = runner.invoke(cli, ["check", "c.yaml"])
            assert result.exit_code == 1
            assert "Missing from_email" in result.output
            assert "Missing subject" in result.output
            assert "No SMTP servers" in result.output


# Test 'test' command


def test_test_smtp_success(runner):
    with runner.isolated_filesystem():
        with open("c.yaml", "w") as f:
            f.write("")

        with patch("mercury.services.campaign_service.load_campaign_from_yaml") as mock_load, patch(
            "mercury.services.smtp_service.SMTPService"
        ) as MockService, patch("asyncio.run") as mock_async_run:
            config = Mock()
            config.smtp_configs = [Mock(name="s1")]
            mock_load.return_value = config

            # Configure service mock
            service_instance = MockService.return_value
            # We mock asyncio.run to return results directly
            mock_async_run.return_value = True  # success

            result = runner.invoke(cli, ["test", "c.yaml"])
            assert "All connections OK!" in result.output


def test_test_smtp_no_servers(runner):
    with runner.isolated_filesystem():
        with open("c.yaml", "w") as f:
            f.write("")
        with patch("mercury.services.campaign_service.load_campaign_from_yaml") as mock_load:
            config = Mock()
            config.smtp_configs = []
            mock_load.return_value = config

            result = runner.invoke(cli, ["test", "c.yaml"])
            assert result.exit_code == 1
            assert "No SMTP servers" in result.output


# Test 'send' command


def test_send_preview(runner):
    with runner.isolated_filesystem():
        with open("c.yaml", "w") as f:
            f.write("")

        with patch("mercury.services.campaign_service.load_campaign_from_yaml") as mock_load, patch(
            "mercury.services.campaign_service.CampaignService"
        ) as MockService:
            config = Mock()
            config.recipients_path = "r.csv"
            mock_load.return_value = config

            service = MockService.return_value
            service.load_recipients_from_csv.return_value = [{"email": "a@b.com"}]

            result = runner.invoke(cli, ["send", "c.yaml", "--preview"])
            assert "PREVIEW" in result.output
            assert "No emails will be sent" in result.output


def test_send_cancel(runner):
    with runner.isolated_filesystem():
        with open("c.yaml", "w") as f:
            f.write("")
        with patch("mercury.services.campaign_service.load_campaign_from_yaml") as mock_load, patch(
            "mercury.services.campaign_service.CampaignService"
        ) as MockService:
            config = Mock()
            config.recipients_path = "r.csv"
            mock_load.return_value = config
            service = MockService.return_value
            service.load_recipients_from_csv.return_value = [{"email": "a@b.com"}]

            # Input 'n' for no
            result = runner.invoke(cli, ["send", "c.yaml"], input="n\n")
            assert "Cancelled" in result.output


def test_send_success(runner):
    with runner.isolated_filesystem():
        with open("c.yaml", "w") as f:
            f.write("")
        with patch("mercury.services.campaign_service.load_campaign_from_yaml") as mock_load, patch(
            "mercury.services.campaign_service.CampaignService"
        ) as MockService, patch("asyncio.run") as mock_run:
            config = Mock()
            config.recipients_path = "r.csv"
            mock_load.return_value = config
            service = MockService.return_value
            service.load_recipients_from_csv.return_value = [{"email": "a@b.com"}]

            mock_run.return_value = {"sent": 1, "failed": 0}

            result = runner.invoke(cli, ["send", "c.yaml", "--yes"])
            assert "Success!" in result.output


# Test 'show' command


def test_show_stats(runner):
    with runner.isolated_filesystem():
        os.makedirs("logs", exist_ok=True)
        with open("logs/success-emails.txt", "w") as f:
            f.write("a\nb\n")
        with open("logs/failed-emails.txt", "w") as f:
            f.write("c\n")

        result = runner.invoke(cli, ["show", "stats"])
        assert "Sent:     2" in result.output
        assert "Failed:   1" in result.output
        assert "Total:    3" in result.output


def test_show_logs(runner):
    with runner.isolated_filesystem():
        os.makedirs("logs", exist_ok=True)
        with open("logs/failed-emails.txt", "w") as f:
            f.write("error\n")

        result = runner.invoke(cli, ["show", "logs"])
        assert "error" in result.output


def test_show_config(runner):
    with runner.isolated_filesystem():
        os.makedirs("config", exist_ok=True)
        with open("config/campaign.yaml", "w") as f:
            f.write("conf: val")

        result = runner.invoke(cli, ["show", "config"])
        assert "conf: val" in result.output


# Test 'start' command


def test_start_server(runner):
    with patch("mercury.web.app.create_app") as mock_create, patch(
        "mercury.web.app.socketio", new=Mock()
    ) as mock_socketio:
        mock_app = Mock()
        mock_create.return_value = mock_app

        result = runner.invoke(cli, ["start", "server"])
        assert "Dashboard" in result.output
        mock_socketio.run.assert_called()


def test_start_server_browser(runner):
    with patch("mercury.web.app.create_app") as mock_create, patch(
        "mercury.web.app.socketio", new=None
    ), patch("webbrowser.open") as mock_browser:
        mock_app = Mock()
        mock_create.return_value = mock_app

        result = runner.invoke(cli, ["start", "server", "--open"])
        mock_browser.assert_called()
        mock_app.run.assert_called()


# Test main entry point
def test_main():
    with patch("mercury.cli.main.cli") as mock_cli:
        main()
        mock_cli.assert_called()


# Test additional CLI paths to bring coverage to 100%

def test_generate_qr(runner):
    with runner.isolated_filesystem():
        with patch("mercury.features.generators.QRCodeGenerator") as MockGen:
            result = runner.invoke(cli, ["generate", "qr", "test_data", "test_qr.png"])
            assert result.exit_code == 0
            assert "Generating QR code for" in result.output
            MockGen.return_value.generate_to_file.assert_called_once_with("test_data", "test_qr.png")

def test_generate_pdf(runner):
    with runner.isolated_filesystem():
        with open("input.html", "w") as f:
            f.write("hello")
        with patch("mercury.features.generators.PDFGenerator") as MockGen:
            result = runner.invoke(cli, ["generate", "pdf", "input.html", "output.pdf"])
            assert result.exit_code == 0
            assert "Converting input.html to PDF" in result.output
            MockGen.return_value.generate_from_html.assert_called_once()

def test_generate_image(runner):
    with runner.isolated_filesystem():
        with open("input.html", "w") as f:
            f.write("hello")
        with patch("mercury.features.generators.ImageGenerator") as MockGen:
            result = runner.invoke(cli, ["generate", "image", "input.html", "output.png"])
            assert result.exit_code == 0
            assert "Converting input.html to Image" in result.output
            MockGen.return_value.generate_from_html.assert_called_once()

def test_db_migrate_success(runner):
    with patch("os.path.isfile", return_value=True), \
         patch("alembic.config.Config") as MockAlembicConfig, \
         patch("alembic.command.upgrade") as mock_upgrade:
        result = runner.invoke(cli, ["db", "migrate", "--revision", "head"])
        assert result.exit_code == 0
        assert "Applying migrations" in result.output
        mock_upgrade.assert_called_once()

def test_db_migrate_uses_packaged_migrations(runner):
    # The command no longer depends on a repo-root alembic.ini (not shipped in
    # the wheel); it resolves the migrations bundled inside the package. Verify
    # upgrade() runs with a config whose script_location is mercury/migrations.
    with patch("alembic.command.upgrade") as mock_up:
        result = runner.invoke(cli, ["db", "migrate"])
        assert result.exit_code == 0, result.output
        cfg = mock_up.call_args.args[0]
        loc = cfg.get_main_option("script_location").replace("\\", "/")
        assert loc.endswith("mercury/migrations")

def test_db_migrate_failed(runner):
    with patch("os.path.isfile", return_value=True), \
         patch("alembic.config.Config"), \
         patch("alembic.command.upgrade", side_effect=Exception("Migration crash")):
        result = runner.invoke(cli, ["db", "migrate"])
        assert result.exit_code == 1
        assert "Migration failed: Migration crash" in result.output

def test_db_current(runner):
    with patch("os.path.isfile", return_value=True), \
         patch("alembic.config.Config"), \
         patch("alembic.command.current") as mock_current:
        result = runner.invoke(cli, ["db", "current"])
        assert result.exit_code == 0
        mock_current.assert_called_once()

def test_cli_options(runner):
    with runner.isolated_filesystem():
        # Test verbose
        result = runner.invoke(cli, ["-v", "new", "config"])
        assert result.exit_code == 0
        # Test quiet
        result = runner.invoke(cli, ["-q", "new", "config"])
        assert result.exit_code == 0

def test_show_nonexistent_file(runner):
    result = runner.invoke(cli, ["show", "logs", "--file", "nonexistent.txt"])
    assert result.exit_code == 0
    assert "No file: nonexistent.txt" in result.output

def test_check_load_exception(runner):
    with runner.isolated_filesystem():
        with open("c.yaml", "w") as f:
            f.write("")
        with patch("mercury.services.campaign_service.load_campaign_from_yaml", side_effect=ValueError("Invalid config syntax")):
            result = runner.invoke(cli, ["check", "c.yaml"])
            assert result.exit_code == 1
            assert "Invalid config syntax" in result.output

def test_test_smtp_failure(runner):
    with runner.isolated_filesystem():
        with open("c.yaml", "w") as f:
            f.write("")
        with patch("mercury.services.campaign_service.load_campaign_from_yaml") as mock_load, \
             patch("mercury.services.smtp_service.SMTPService") as MockService, \
             patch("asyncio.run") as mock_async_run:
            config = Mock()
            config.smtp_configs = [Mock(name="s1")]
            mock_load.return_value = config
            
            # Make asyncio.run return False (failure in connections)
            mock_async_run.return_value = False
            
            result = runner.invoke(cli, ["test", "c.yaml"])
            assert result.exit_code == 1
            assert "Some connections failed" in result.output

def test_send_no_recipients(runner):
    with runner.isolated_filesystem():
        with open("c.yaml", "w") as f:
            f.write("")
        with patch("mercury.services.campaign_service.load_campaign_from_yaml") as mock_load, \
             patch("mercury.services.campaign_service.CampaignService") as MockService:
            config = Mock()
            config.recipients_path = None
            mock_load.return_value = config
            
            result = runner.invoke(cli, ["send", "c.yaml"])
            assert result.exit_code == 1
            assert "No recipients file" in result.output

def test_send_limit_and_txt_source(runner):
    with runner.isolated_filesystem():
        with open("c.yaml", "w") as f:
            f.write("")
        with patch("mercury.services.campaign_service.load_campaign_from_yaml") as mock_load, \
             patch("mercury.services.campaign_service.CampaignService") as MockService, \
             patch("asyncio.run") as mock_run:
            config = Mock()
            config.recipients_path = "r.txt" # ends with text
            config.email_column = "email"
            mock_load.return_value = config
            
            service = MockService.return_value
            service.load_recipients_from_text.return_value = [
                {"email": "1@b.com"}, {"email": "2@b.com"}, {"email": "3@b.com"}
            ]
            mock_run.return_value = {"sent": 2, "failed": 0}
            
            result = runner.invoke(cli, ["send", "c.yaml", "--to", "2", "--yes"])
            assert result.exit_code == 0
            assert "Sent: 2" in result.output
            service.load_recipients_from_text.assert_called_once_with("r.txt")

def test_send_failures_warning(runner):
    with runner.isolated_filesystem():
        with open("c.yaml", "w") as f:
            f.write("")
        with patch("mercury.services.campaign_service.load_campaign_from_yaml") as mock_load, \
             patch("mercury.services.campaign_service.CampaignService") as MockService, \
             patch("asyncio.run") as mock_run:
            config = Mock()
            config.recipients_path = "r.csv"
            config.email_column = "email"
            mock_load.return_value = config
            
            service = MockService.return_value
            service.load_recipients_from_csv.return_value = [{"email": "1@b.com"}]
            mock_run.return_value = {"sent": 0, "failed": 1}
            
            result = runner.invoke(cli, ["send", "c.yaml", "--yes"])
            assert result.exit_code == 0
            assert "Check logs/failed-emails.txt" in result.output

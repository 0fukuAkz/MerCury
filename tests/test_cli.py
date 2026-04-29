"""Tests for CLI."""

import os
from unittest.mock import patch, Mock, MagicMock
from click.testing import CliRunner
import pytest

from mercury.cli.main import cli, main

@pytest.fixture
def runner():
    return CliRunner()

# Test 'new' command

def test_new_project(runner):
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ['new', 'project'])
        assert result.exit_code == 0
        assert "Done!" in result.output
        assert os.path.exists('config/campaign.yaml')
        assert os.path.exists('templates/email.html')
        assert os.path.exists('data/recipients.csv')

def test_new_config_force(runner):
    with runner.isolated_filesystem():
        os.makedirs('config')
        with open('config/campaign.yaml', 'w') as f:
            f.write("old")
            
        # Without force
        result = runner.invoke(cli, ['new', 'config'])
        assert "exists" in result.output
        
        # With force
        result = runner.invoke(cli, ['new', 'config', '--force'])
        assert "Created" in result.output

def test_new_template(runner):
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ['new', 'template', '--name', 'welcome'])
        assert os.path.exists('templates/welcome.html')

# Test 'check' command

def test_check_valid_config(runner):
    with runner.isolated_filesystem():
        # Setup valid files
        os.makedirs('data')
        with open('data/recipients.csv', 'w') as f: f.write("a\nb")
        with open('c.yaml', 'w') as f: f.write("") # Create dummy config file
            
        with patch('mercury.services.campaign_service.load_campaign_from_yaml') as mock_load:
            config = Mock()
            config.name = "Test"
            config.from_email = "f@e.com"
            config.subject = "Sub"
            config.template_path = "t.html"
            config.recipients_path = "data/recipients.csv"
            config.smtp_configs = [Mock()]
            mock_load.return_value = config
            
            with patch('os.path.exists', return_value=True):
                 result = runner.invoke(cli, ['check', 'c.yaml'])
            
            assert result.exit_code == 0
            assert "All good!" in result.output

def test_check_invalid_config(runner):
    with runner.isolated_filesystem():
        with patch('mercury.services.campaign_service.load_campaign_from_yaml') as mock_load:
            config = Mock()
            config.name = "" # invalid
            config.from_email = "" 
            config.subject = ""
            config.template_path = "missing.html"
            config.recipients_path = "missing.csv"
            config.smtp_configs = []
            mock_load.return_value = config
            
            # Use os.path.exists real behavior (files don't exist in isolated fs)
            # Except we need 'c.yaml' to exist for click argument validity?
            # Click argument `type=click.Path(exists=True)` handles check before invoking function.
            with open('c.yaml', 'w') as f: f.write("")
            
            result = runner.invoke(cli, ['check', 'c.yaml'])
            assert result.exit_code == 1
            assert "Missing from_email" in result.output
            assert "Missing subject" in result.output
            assert "No SMTP servers" in result.output

# Test 'test' command

def test_test_smtp_success(runner):
    with runner.isolated_filesystem():
        with open('c.yaml', 'w') as f: f.write("")
        
        with patch('mercury.services.campaign_service.load_campaign_from_yaml') as mock_load, \
             patch('mercury.services.smtp_service.SMTPService') as MockService, \
             patch('asyncio.run') as mock_async_run:
            
            config = Mock()
            config.smtp_configs = [Mock(name='s1')]
            mock_load.return_value = config
            
            # Configure service mock
            service_instance = MockService.return_value
            # We mock asyncio.run to return results directly
            mock_async_run.return_value = True # success
            
            result = runner.invoke(cli, ['test', 'c.yaml'])
            assert "All connections OK!" in result.output

def test_test_smtp_no_servers(runner):
    with runner.isolated_filesystem():
        with open('c.yaml', 'w') as f: f.write("")
        with patch('mercury.services.campaign_service.load_campaign_from_yaml') as mock_load:
            config = Mock()
            config.smtp_configs = []
            mock_load.return_value = config
            
            result = runner.invoke(cli, ['test', 'c.yaml'])
            assert result.exit_code == 1
            assert "No SMTP servers" in result.output

# Test 'send' command

def test_send_preview(runner):
    with runner.isolated_filesystem():
        with open('c.yaml', 'w') as f: f.write("")
        
        with patch('mercury.services.campaign_service.load_campaign_from_yaml') as mock_load, \
             patch('mercury.services.campaign_service.CampaignService') as MockService:
            
            config = Mock()
            config.recipients_path = "r.csv"
            mock_load.return_value = config
            
            service = MockService.return_value
            service.load_recipients_from_csv.return_value = [{'email': 'a@b.com'}]
            
            result = runner.invoke(cli, ['send', 'c.yaml', '--preview'])
            assert "PREVIEW" in result.output
            assert "No emails will be sent" in result.output

def test_send_cancel(runner):
    with runner.isolated_filesystem():
        with open('c.yaml', 'w') as f: f.write("")
        with patch('mercury.services.campaign_service.load_campaign_from_yaml') as mock_load, \
             patch('mercury.services.campaign_service.CampaignService') as MockService:
             
            config = Mock()
            config.recipients_path = "r.csv"
            mock_load.return_value = config
            service = MockService.return_value
            service.load_recipients_from_csv.return_value = [{'email': 'a@b.com'}]
            
            # Input 'n' for no
            result = runner.invoke(cli, ['send', 'c.yaml'], input='n\n')
            assert "Cancelled" in result.output

def test_send_success(runner):
    with runner.isolated_filesystem():
        with open('c.yaml', 'w') as f: f.write("")
        with patch('mercury.services.campaign_service.load_campaign_from_yaml') as mock_load, \
             patch('mercury.services.campaign_service.CampaignService') as MockService, \
             patch('asyncio.run') as mock_run:
             
            config = Mock()
            config.recipients_path = "r.csv"
            mock_load.return_value = config
            service = MockService.return_value
            service.load_recipients_from_csv.return_value = [{'email': 'a@b.com'}]
            
            mock_run.return_value = {'sent': 1, 'failed': 0}
            
            result = runner.invoke(cli, ['send', 'c.yaml', '--yes'])
            assert "Success!" in result.output

# Test 'show' command

def test_show_stats(runner):
    with runner.isolated_filesystem():
        os.makedirs('logs', exist_ok=True)
        with open('logs/success-emails.txt', 'w') as f: f.write("a\nb\n")
        with open('logs/failed-emails.txt', 'w') as f: f.write("c\n")
        
        result = runner.invoke(cli, ['show', 'stats'])
        assert "Sent:     2" in result.output
        assert "Failed:   1" in result.output
        assert "Total:    3" in result.output

def test_show_logs(runner):
    with runner.isolated_filesystem():
        os.makedirs('logs', exist_ok=True)
        with open('logs/failed-emails.txt', 'w') as f: f.write("error\n")
        
        result = runner.invoke(cli, ['show', 'logs'])
        assert "error" in result.output

def test_show_config(runner):
     with runner.isolated_filesystem():
        os.makedirs('config', exist_ok=True)
        with open('config/campaign.yaml', 'w') as f: f.write("conf: val")
        
        result = runner.invoke(cli, ['show', 'config'])
        assert "conf: val" in result.output

# Test 'start' command

def test_start_server(runner):
    with patch('mercury.web.app.create_app') as mock_create, \
         patch('mercury.web.app.socketio', new=Mock()) as mock_socketio:
        
        mock_app = Mock()
        mock_create.return_value = mock_app
        
        result = runner.invoke(cli, ['start', 'server'])
        assert "Dashboard" in result.output
        mock_socketio.run.assert_called()

def test_start_server_browser(runner):
    with patch('mercury.web.app.create_app') as mock_create, \
         patch('mercury.web.app.socketio', new=None), \
         patch('webbrowser.open') as mock_browser:
        
        mock_app = Mock()
        mock_create.return_value = mock_app
        
        result = runner.invoke(cli, ['start', 'server', '--open'])
        mock_browser.assert_called()
        mock_app.run.assert_called()

# Test main entry point
def test_main():
    with patch('mercury.cli.main.cli') as mock_cli:
        main()
        mock_cli.assert_called()

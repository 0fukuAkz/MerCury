"""Tests for Configuration Overhaul features."""

import pytest
from mercury.services.identity_service import IdentityService
from mercury.services.settings_service import SettingsService
from mercury.services.campaign_service import CampaignService, CampaignConfig
from mercury.data.models.identity import FromEmail, SenderName
from mercury.data.models.settings import GlobalSetting

def test_identity_service_emails(app):
    """Test identity service email operations."""
    with app.app_context():
        # Add
        email = IdentityService.add_email("test@example.com", ["test"])
        assert email.email == "test@example.com"
        assert "test" in email.tags
        assert email.is_active

        # Get
        emails = IdentityService.get_emails()
        assert len(emails) == 1
        assert emails[0].email == "test@example.com"

        # Toggle
        updated = IdentityService.toggle_email_status(email.id)
        assert not updated.is_active

        # Delete
        assert IdentityService.delete_email(email.id)
        assert len(IdentityService.get_emails()) == 0

def test_identity_service_names(app):
    """Test identity service name operations."""
    with app.app_context():
        # Add
        name = IdentityService.add_name("John Doe", ["marketing"])
        assert name.name == "John Doe"
        
        # Get
        names = IdentityService.get_names()
        assert len(names) == 1
        
        # Toggle
        IdentityService.toggle_name_status(name.id)
        names = IdentityService.get_names(active_only=True)
        assert len(names) == 0

def test_settings_service(app):
    """Test global settings service."""
    with app.app_context():
        # Get defaults
        settings = SettingsService.get_settings()
        assert settings.daily_limit == 500
        assert settings.max_retries == 3
        
        # Update
        updated = SettingsService.update_settings({
            'daily_limit': 1000,
            'max_concurrency': 10
        })
        assert updated.daily_limit == 1000
        assert updated.max_concurrency == 10
        
        # Verify persistence
        refetched = SettingsService.get_settings()
        assert refetched.daily_limit == 1000

def test_campaign_service_resolves_identities(app):
    """Test that CampaignService picks up identities from the pool."""
    service = CampaignService()
    
    with app.app_context():
        # Setup pool
        IdentityService.add_email("pool@example.com")
        IdentityService.add_name("Pool Sender")
        SettingsService.update_settings({'default_reply_to': 'reply@example.com'})
        
        # Load config with empty sender
        config = CampaignConfig(name="Test Campaign")
        service.load_config(config)
        
        # Verify resolution
        assert service.config.from_email == "pool@example.com"
        assert service.config.from_name == "Pool Sender"
        assert service.config.reply_to == "reply@example.com"

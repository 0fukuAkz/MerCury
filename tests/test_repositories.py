"""Tests for repository layer."""

import pytest
from datetime import datetime, UTC

from unified_sender.data.models.campaign import Campaign, CampaignStatus
from unified_sender.data.models.recipient import Recipient
from unified_sender.data.models.smtp import SMTPServer
from unified_sender.data.models.template import EmailTemplate
from unified_sender.data.repositories.campaign import CampaignRepository
from unified_sender.data.repositories.recipient import RecipientRepository
from unified_sender.data.repositories.smtp import SMTPRepository
from unified_sender.data.repositories.template import TemplateRepository


class TestBaseRepository:
    """Test base repository CRUD operations."""
    
    def test_create(self, db_session):
        """Test creating an entity."""
        repo = SMTPRepository(db_session)
        
        smtp = SMTPServer(
            name="test-smtp",
            host="smtp.example.com",
            port=587,
            username="test@example.com",
            password="encrypted_pass",
            use_tls=True
        )
        
        created = repo.create(smtp)
        
        assert created.id is not None
        assert created.name == "test-smtp"
        assert created.host == "smtp.example.com"
    
    def test_get_by_id(self, db_session):
        """Test retrieving entity by ID."""
        repo = SMTPRepository(db_session)
        
        smtp = SMTPServer(name="test", host="smtp.test.com", port=587)
        created = repo.create(smtp)
        
        retrieved = repo.get(created.id)
        
        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.name == "test"
    
    def test_get_all(self, db_session):
        """Test retrieving all entities."""
        repo = SMTPRepository(db_session)
        
        smtp1 = SMTPServer(name="smtp1", host="smtp1.com", port=587)
        smtp2 = SMTPServer(name="smtp2", host="smtp2.com", port=465)
        
        repo.create(smtp1)
        repo.create(smtp2)
        
        all_servers = repo.get_all()
        
        assert len(all_servers) == 2
    
    def test_update(self, db_session):
        """Test updating an entity."""
        repo = SMTPRepository(db_session)
        
        smtp = SMTPServer(name="test", host="smtp.test.com", port=587)
        created = repo.create(smtp)
        
        created.port = 465
        updated = repo.update(created)
        
        assert updated.port == 465
    
    def test_delete(self, db_session):
        """Test deleting an entity."""
        repo = SMTPRepository(db_session)
        
        smtp = SMTPServer(name="test", host="smtp.test.com", port=587)
        created = repo.create(smtp)
        
        result = repo.delete(created)
        
        assert result is True
        assert repo.get(created.id) is None
    
    def test_count(self, db_session):
        """Test counting entities."""
        repo = SMTPRepository(db_session)
        
        smtp1 = SMTPServer(name="smtp1", host="smtp1.com", port=587)
        smtp2 = SMTPServer(name="smtp2", host="smtp2.com", port=465)
        
        repo.create(smtp1)
        repo.create(smtp2)
        
        count = repo.count()
        
        assert count == 2
    
    def test_exists(self, db_session):
        """Test checking entity existence."""
        repo = SMTPRepository(db_session)
        
        smtp = SMTPServer(name="test", host="smtp.test.com", port=587)
        created = repo.create(smtp)
        
        assert repo.exists(created.id) is True
        assert repo.exists(99999) is False


class TestCampaignRepository:
    """Test campaign repository."""
    
    def test_get_by_name(self, db_session):
        """Test getting campaign by name."""
        repo = CampaignRepository(db_session)
        
        campaign = Campaign(
            name="Test Campaign",
            status=CampaignStatus.DRAFT,
            subject="Test Subject",
            created_at=datetime.now(UTC)
        )
        repo.create(campaign)
        
        found = repo.get_by_name("Test Campaign")
        
        assert found is not None
        assert found.name == "Test Campaign"
    
    def test_get_by_status(self, db_session):
        """Test getting campaigns by status."""
        repo = CampaignRepository(db_session)
        
        draft = Campaign(
            name="Draft Campaign",
            status=CampaignStatus.DRAFT,
            subject="Test",
            created_at=datetime.now(UTC)
        )
        running = Campaign(
            name="Running Campaign",
            status=CampaignStatus.RUNNING,
            subject="Test",
            created_at=datetime.now(UTC)
        )
        
        repo.create(draft)
        repo.create(running)
        
        drafts = repo.get_by_status(CampaignStatus.DRAFT)
        
        assert len(drafts) == 1
        assert drafts[0].name == "Draft Campaign"


class TestRecipientRepository:
    """Test recipient repository."""
    
    def test_get_by_email(self, db_session):
        """Test getting recipient by email."""
        repo = RecipientRepository(db_session)
        
        recipient = Recipient(
            email="test@example.com",
            first_name="John"
        )
        repo.create(recipient)
        
        found = repo.get_by_email("test@example.com")
        
        assert found is not None
        assert found.email == "test@example.com"
        assert found.first_name == "John"
    
    def test_bulk_create(self, db_session):
        """Test bulk recipient creation."""
        repo = RecipientRepository(db_session)
        
        recipients = [
            Recipient(email=f"user{i}@test.com")
            for i in range(10)
        ]
        
        created = repo.bulk_create(recipients)
        
        assert len(created) == 10
        assert all(r.id is not None for r in created)


class TestTemplateRepository:
    """Test template repository."""
    
    def test_get_by_name(self, db_session):
        """Test getting template by name."""
        repo = TemplateRepository(db_session)
        
        template = EmailTemplate(
            name="Welcome Email",
            subject="Welcome!",
            html_content="<p>Welcome {{name}}!</p>"
        )
        repo.create(template)
        
        found = repo.get_by_name("Welcome Email")
        
        assert found is not None
        assert found.name == "Welcome Email"
        assert "{{name}}" in found.html_content


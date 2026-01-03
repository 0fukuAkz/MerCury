"""Tests for dead letter service."""

import pytest
from datetime import datetime, UTC

from mercury.services.dead_letter_service import DeadLetterService
from mercury.data.repositories.dead_letter import DeadLetterRepository
from mercury.data.models.dead_letter import DeadLetter


class TestDeadLetterService:
    """Test dead letter service."""
    
    def test_add_dead_letter(self, db_session):
        """Test adding email to dead letter queue."""
        repo = DeadLetterRepository(db_session)
        service = DeadLetterService(repo)
        
        dead_letter = service.add_dead_letter(
            recipient="failed@example.com",
            subject="Test Email",
            html_body="<p>Test</p>",
            from_email="sender@example.com",
            error_type="SMTPMailboxError",
            error_message="Mailbox does not exist"
        )
        
        assert dead_letter.id is not None
        assert dead_letter.recipient == "failed@example.com"
        assert dead_letter.resolved is False
    
    def test_get_unresolved(self, db_session):
        """Test getting unresolved dead letters."""
        repo = DeadLetterRepository(db_session)
        service = DeadLetterService(repo)
        
        # Add several dead letters
        for i in range(3):
            service.add_dead_letter(
                recipient=f"user{i}@test.com",
                subject="Test",
                html_body="<p>Test</p>",
                from_email="sender@test.com",
                error_type="SMTPError",
                error_message="Error"
            )
        
        # Get unresolved
        unresolved = service.get_unresolved()
        
        assert len(unresolved) == 3
        assert all(not dl.resolved for dl in unresolved)
    
    def test_mark_resolved(self, db_session):
        """Test marking dead letter as resolved."""
        repo = DeadLetterRepository(db_session)
        service = DeadLetterService(repo)
        
        # Add dead letter
        dead_letter = service.add_dead_letter(
            recipient="failed@test.com",
            subject="Test",
            html_body="<p>Test</p>",
            from_email="sender@test.com",
            error_type="SMTPError",
            error_message="Error"
        )
        
        # Mark resolved
        updated = service.mark_resolved(
            dead_letter.id,
            resolution_notes="Fixed recipient email"
        )
        
        assert updated is not None
        assert updated.resolved is True
        assert updated.resolved_at is not None
        assert updated.resolution_notes == "Fixed recipient email"
    
    def test_get_by_error_type(self, db_session):
        """Test filtering by error type."""
        repo = DeadLetterRepository(db_session)
        service = DeadLetterService(repo)
        
        # Add different error types
        service.add_dead_letter(
            recipient="user1@test.com",
            subject="Test",
            html_body="<p>Test</p>",
            from_email="sender@test.com",
            error_type="SMTPConnectionError",
            error_message="Connection failed"
        )
        
        service.add_dead_letter(
            recipient="user2@test.com",
            subject="Test",
            html_body="<p>Test</p>",
            from_email="sender@test.com",
            error_type="SMTPAuthenticationError",
            error_message="Auth failed"
        )
        
        # Get by type
        conn_errors = service.get_by_error_type("SMTPConnectionError")
        
        assert len(conn_errors) == 1
        assert conn_errors[0].error_type == "SMTPConnectionError"
    
    def test_retry_tracking(self, db_session):
        """Test tracking retry attempts."""
        repo = DeadLetterRepository(db_session)
        service = DeadLetterService(repo)
        
        dead_letter = service.add_dead_letter(
            recipient="failed@test.com",
            subject="Test",
            html_body="<p>Test</p>",
            from_email="sender@test.com",
            error_type="SMTPError",
            error_message="Error"
        )
        
        assert dead_letter.retry_count == 0
        
        # Increment retry
        updated = service.retry_dead_letter(dead_letter.id)
        
        assert updated.retry_count == 1
        assert updated.last_retry_at is not None
    
    def test_statistics(self, db_session):
        """Test getting statistics."""
        repo = DeadLetterRepository(db_session)
        service = DeadLetterService(repo)
        
        # Add some dead letters
        for i in range(5):
            dl = service.add_dead_letter(
                recipient=f"user{i}@test.com",
                subject="Test",
                html_body="<p>Test</p>",
                from_email="sender@test.com",
                error_type="SMTPError" if i < 3 else "MailboxError",
                error_message="Error"
            )
            
            # Resolve some
            if i < 2:
                service.mark_resolved(dl.id)
        
        stats = service.get_statistics()
        
        assert stats['total'] == 5
        assert stats['resolved'] == 2
        assert stats['unresolved'] == 3
        assert 'by_error_type' in stats


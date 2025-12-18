"""Tests for error aggregator."""

import pytest
from datetime import datetime, UTC

from unified_sender.engine.error_aggregator import ErrorAggregator, ErrorGroup
from unified_sender.exceptions import (
    SMTPConnectionError,
    SMTPAuthenticationError,
    SMTPMailboxError,
    TransientSMTPError
)


class TestErrorAggregator:
    """Test error aggregation functionality."""
    
    def test_add_single_error(self):
        """Test adding single error."""
        aggregator = ErrorAggregator()
        
        error = SMTPConnectionError("Connection failed")
        aggregator.add_error(error, "user@test.com", is_transient=True)
        
        summary = aggregator.get_summary()
        
        assert summary.total_errors == 1
        assert summary.unique_error_types == 1
        assert summary.transient_count == 1
    
    def test_groups_similar_errors(self):
        """Test grouping similar errors together."""
        aggregator = ErrorAggregator()
        
        # Add same error type multiple times
        for i in range(5):
            error = SMTPConnectionError(f"Connection failed #{i}")
            aggregator.add_error(error, f"user{i}@test.com", is_transient=True)
        
        summary = aggregator.get_summary()
        
        assert summary.total_errors == 5
        assert summary.unique_error_types == 1  # All grouped together
        assert len(summary.groups) == 1
        assert summary.groups[0].count == 5
    
    def test_separates_different_errors(self):
        """Test different error types are separated."""
        aggregator = ErrorAggregator()
        
        # Add different error types
        aggregator.add_error(
            SMTPConnectionError("Connection failed"),
            "user1@test.com",
            is_transient=True
        )
        aggregator.add_error(
            SMTPAuthenticationError("Auth failed"),
            "user2@test.com",
            is_transient=False
        )
        aggregator.add_error(
            SMTPMailboxError("Mailbox not found"),
            "user3@test.com",
            is_transient=False
        )
        
        summary = aggregator.get_summary()
        
        assert summary.total_errors == 3
        assert summary.unique_error_types == 3
        assert len(summary.groups) == 3
    
    def test_transient_vs_permanent_counts(self):
        """Test counting transient vs permanent errors."""
        aggregator = ErrorAggregator()
        
        # Add transient errors
        for i in range(3):
            aggregator.add_error(
                TransientSMTPError("Temp error"),
                f"user{i}@test.com",
                is_transient=True
            )
        
        # Add permanent errors
        for i in range(2):
            aggregator.add_error(
                SMTPAuthenticationError("Auth failed"),
                f"admin{i}@test.com",
                is_transient=False
            )
        
        summary = aggregator.get_summary()
        
        assert summary.transient_count == 3
        assert summary.permanent_count == 2
    
    def test_top_errors(self):
        """Test getting most common errors."""
        aggregator = ErrorAggregator()
        
        # Add errors with different frequencies
        for _ in range(10):
            aggregator.add_error(
                SMTPConnectionError("Connection error"),
                "user@test.com",
                is_transient=True
            )
        
        for _ in range(5):
            aggregator.add_error(
                SMTPAuthenticationError("Auth error"),
                "user@test.com",
                is_transient=False
            )
        
        for _ in range(2):
            aggregator.add_error(
                SMTPMailboxError("Mailbox error"),
                "user@test.com",
                is_transient=False
            )
        
        top = aggregator.get_top_errors(limit=2)
        
        assert len(top) == 2
        assert top[0].count == 10  # Connection error (most common)
        assert top[1].count == 5   # Auth error (second)
    
    def test_critical_errors_detection(self):
        """Test detecting critical error patterns."""
        aggregator = ErrorAggregator()
        
        # Add mostly permanent errors (should be critical)
        for _ in range(8):
            aggregator.add_error(
                SMTPAuthenticationError("Auth failed"),
                "user@test.com",
                is_transient=False
            )
        
        # Add few transient
        for _ in range(2):
            aggregator.add_error(
                TransientSMTPError("Temp error"),
                "user@test.com",
                is_transient=True
            )
        
        # >50% permanent = critical
        assert aggregator.has_critical_errors() is True
    
    def test_recommendations(self):
        """Test getting recommendations based on errors."""
        aggregator = ErrorAggregator()
        
        # Add authentication errors
        aggregator.add_error(
            SMTPAuthenticationError("Auth failed", smtp_server="smtp1"),
            "user@test.com",
            smtp_server="smtp1",
            is_transient=False
        )
        
        recommendations = aggregator.get_recommendations()
        
        # Should recommend checking credentials
        assert any('credentials' in r.lower() for r in recommendations)
    
    def test_smtp_server_tracking(self):
        """Test tracking which SMTP servers failed."""
        aggregator = ErrorAggregator()
        
        error = SMTPConnectionError("Connection failed")
        
        aggregator.add_error(error, "user1@test.com", smtp_server="smtp1", is_transient=True)
        aggregator.add_error(error, "user2@test.com", smtp_server="smtp2", is_transient=True)
        aggregator.add_error(error, "user3@test.com", smtp_server="smtp1", is_transient=True)
        
        summary = aggregator.get_summary()
        group = summary.groups[0]
        
        assert "smtp1" in group.smtp_servers
        assert "smtp2" in group.smtp_servers
        assert len(group.recipients) == 3


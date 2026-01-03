"""Tests for error recovery manager."""

import pytest

from mercury.engine.error_recovery import (
    ErrorRecoveryManager,
    ErrorRecoveryDecision,
    RecoveryStrategy
)
from mercury.exceptions import (
    SMTPConnectionError,
    SMTPAuthenticationError,
    SMTPMailboxError,
    TransientSMTPError,
    PermanentSMTPError
)


class TestErrorRecoveryManager:
    """Test error recovery manager."""
    
    def test_permanent_error_to_dead_letter(self):
        """Test permanent errors go to dead letter queue."""
        manager = ErrorRecoveryManager()
        
        error = SMTPAuthenticationError("Auth failed", is_transient=False)
        decision = manager.decide_recovery(error)
        
        assert decision.should_retry is False
        assert decision.strategy in [RecoveryStrategy.DEAD_LETTER, RecoveryStrategy.ALERT]
    
    def test_transient_error_retries(self):
        """Test transient errors trigger retry."""
        manager = ErrorRecoveryManager()
        
        error = SMTPConnectionError("Timeout", is_transient=True)
        decision = manager.decide_recovery(error)
        
        assert decision.should_retry is True
    
    def test_smtp_server_switching(self):
        """Test switching to alternative SMTP server."""
        manager = ErrorRecoveryManager(
            available_smtp_servers=["smtp1", "smtp2", "smtp3"]
        )
        
        error = TransientSMTPError("Server busy")
        decision = manager.decide_recovery(
            error,
            current_smtp="smtp1",
            correlation_id="test-123"
        )
        
        assert decision.strategy == RecoveryStrategy.SWITCH_SERVER
        assert decision.alternative_smtp in ["smtp2", "smtp3"]
        assert decision.should_retry is True
    
    def test_max_switches_enforced(self):
        """Test max server switches is enforced."""
        manager = ErrorRecoveryManager(
            available_smtp_servers=["smtp1", "smtp2", "smtp3"],
            max_smtp_switches=2
        )
        
        correlation_id = "test-123"
        error = TransientSMTPError("Error")
        
        # First switch
        decision1 = manager.decide_recovery(
            error, current_smtp="smtp1", correlation_id=correlation_id
        )
        assert decision1.strategy == RecoveryStrategy.SWITCH_SERVER
        
        # Second switch
        decision2 = manager.decide_recovery(
            error, current_smtp="smtp2", correlation_id=correlation_id
        )
        assert decision2.strategy == RecoveryStrategy.SWITCH_SERVER
        
        # Third attempt - should delay instead of switch
        decision3 = manager.decide_recovery(
            error, current_smtp="smtp3", correlation_id=correlation_id
        )
        assert decision3.strategy == RecoveryStrategy.DELAY_RETRY
    
    def test_tracks_attempted_servers(self):
        """Test tracking which servers were attempted."""
        manager = ErrorRecoveryManager(
            available_smtp_servers=["smtp1", "smtp2"]
        )
        
        correlation_id = "test-123"
        error = TransientSMTPError("Error")
        
        # Try first server
        manager.decide_recovery(error, current_smtp="smtp1", correlation_id=correlation_id)
        
        # Check attempted servers
        attempted = manager.get_attempted_servers(correlation_id)
        assert "smtp1" in attempted
    
    def test_clear_tracking(self):
        """Test clearing recovery tracking."""
        manager = ErrorRecoveryManager(
            available_smtp_servers=["smtp1", "smtp2"]
        )
        
        correlation_id = "test-123"
        error = TransientSMTPError("Error")
        
        # Make some attempts
        manager.decide_recovery(error, current_smtp="smtp1", correlation_id=correlation_id)
        manager.decide_recovery(error, current_smtp="smtp2", correlation_id=correlation_id)
        
        # Clear tracking
        manager.clear_tracking(correlation_id)
        
        # Should be reset
        assert len(manager.get_attempted_servers(correlation_id)) == 0
    
    def test_fallback_chain(self):
        """Test fallback chain through all servers."""
        manager = ErrorRecoveryManager(
            available_smtp_servers=["smtp1", "smtp2", "smtp3"]
        )
        
        correlation_id = "test-123"
        error = TransientSMTPError("Error")
        
        decisions = []
        current_smtp = "smtp1"
        
        for _ in range(3):
            decision = manager.decide_recovery(
                error,
                current_smtp=current_smtp,
                correlation_id=correlation_id
            )
            decisions.append(decision)
            
            if decision.alternative_smtp:
                current_smtp = decision.alternative_smtp
        
        # Should have tried switching
        switches = [d for d in decisions if d.strategy == RecoveryStrategy.SWITCH_SERVER]
        assert len(switches) >= 1
    
    def test_statistics(self):
        """Test getting recovery statistics."""
        manager = ErrorRecoveryManager(
            available_smtp_servers=["smtp1", "smtp2"]
        )
        
        error = TransientSMTPError("Error")
        manager.decide_recovery(error, current_smtp="smtp1", correlation_id="test-1")
        manager.decide_recovery(error, current_smtp="smtp1", correlation_id="test-2")
        
        stats = manager.get_statistics()
        
        assert 'active_recoveries' in stats
        assert 'total_switches' in stats
        assert 'available_servers' in stats
        assert stats['available_servers'] == 2


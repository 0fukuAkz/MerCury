"""
Demonstration of advanced error handling features.

This example shows how to use all 5 error handling layers:
1. Custom exceptions
2. Circuit breaker
3. Error recovery
4. Dead letter queue
5. Error aggregation
"""

import asyncio
from datetime import datetime, UTC

# Import error handling components
from unified_sender.engine.enhanced_sender import EnhancedAsyncEmailSender
from unified_sender.engine.connection_pool import SMTPConnectionPool, SMTPServerConfig
from unified_sender.engine.error_recovery import ErrorRecoveryManager
from unified_sender.services.dead_letter_service import DeadLetterService
from unified_sender.data.repositories.dead_letter import DeadLetterRepository
from unified_sender.data.database import get_session
from unified_sender.exceptions import (
    SMTPConnectionError,
    SMTPAuthenticationError,
    is_transient_error
)
from unified_sender.utils.logging_context import (
    configure_structured_logging,
    EmailOperationContext
)


async def demo_basic_exceptions():
    """Demo: Using custom exceptions."""
    print("\n" + "="*60)
    print("DEMO 1: Custom Exceptions")
    print("="*60)
    
    try:
        # Simulate an error
        raise SMTPConnectionError(
            "Connection timeout",
            smtp_server="smtp.example.com",
            smtp_response="Timeout after 30s"
        )
    except SMTPConnectionError as e:
        print(f"❌ Error: {e.message}")
        print(f"   Server: {e.smtp_server}")
        print(f"   Transient: {e.is_transient}")
        print(f"   Details: {e.details}")
        
        if is_transient_error(e):
            print("   ✅ Can retry this error")


async def demo_circuit_breaker():
    """Demo: Circuit breaker protecting SMTP server."""
    print("\n" + "="*60)
    print("DEMO 2: Circuit Breaker")
    print("="*60)
    
    from unified_sender.engine.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
    
    config = CircuitBreakerConfig(
        failure_threshold=3,
        success_threshold=2,
        timeout_seconds=5
    )
    
    cb = CircuitBreaker("demo-smtp", config)
    
    print(f"Initial state: {cb._stats.state.value}")
    
    # Simulate failures
    for i in range(4):
        cb.record_failure(SMTPConnectionError(f"Error {i}"))
        print(f"After failure {i+1}: {cb._stats.state.value}, Available: {cb.is_available()}")
    
    # Wait for timeout
    print("\nWaiting for circuit to enter half-open...")
    await asyncio.sleep(5.5)
    
    print(f"After timeout: Available: {cb.is_available()}")
    
    # Successful recovery
    cb.record_success()
    cb.record_success()
    print(f"After 2 successes: {cb._stats.state.value}")


async def demo_error_recovery():
    """Demo: Automatic error recovery with SMTP switching."""
    print("\n" + "="*60)
    print("DEMO 3: Error Recovery")
    print("="*60)
    
    from unified_sender.engine.error_recovery import ErrorRecoveryManager
    from unified_sender.exceptions import TransientSMTPError
    
    manager = ErrorRecoveryManager(
        available_smtp_servers=["smtp1.example.com", "smtp2.example.com", "smtp3.example.com"],
        max_smtp_switches=2
    )
    
    correlation_id = "demo-email-123"
    error = TransientSMTPError("Server overloaded")
    
    # First attempt
    decision1 = manager.decide_recovery(
        error,
        current_smtp="smtp1.example.com",
        correlation_id=correlation_id
    )
    
    print(f"Decision 1: {decision1.strategy.value}")
    print(f"  Should retry: {decision1.should_retry}")
    print(f"  Alternative: {decision1.alternative_smtp}")
    print(f"  Reason: {decision1.reason}")
    
    # Second attempt (after switch)
    decision2 = manager.decide_recovery(
        error,
        current_smtp=decision1.alternative_smtp,
        correlation_id=correlation_id
    )
    
    print(f"\nDecision 2: {decision2.strategy.value}")
    print(f"  Alternative: {decision2.alternative_smtp}")
    
    # Check what we've tried
    attempted = manager.get_attempted_servers(correlation_id)
    print(f"\nServers attempted: {attempted}")


def demo_dead_letter_queue():
    """Demo: Dead letter queue for permanent failures."""
    print("\n" + "="*60)
    print("DEMO 4: Dead Letter Queue")
    print("="*60)
    
    # Create in-memory database for demo
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from unified_sender.data.database import Base
    
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    
    # Setup service
    repo = DeadLetterRepository(session)
    service = DeadLetterService(repo)
    
    # Add failed emails
    for i in range(5):
        service.add_dead_letter(
            recipient=f"invalid{i}@example.com",
            subject="Welcome Email",
            html_body="<p>Welcome!</p>",
            from_email="sender@example.com",
            error_type="SMTPMailboxError" if i < 3 else "SMTPAuthenticationError",
            error_message="550 Mailbox does not exist" if i < 3 else "535 Auth failed"
        )
    
    # Get statistics
    stats = service.get_statistics()
    print(f"Total dead letters: {stats['total']}")
    print(f"By error type: {stats['by_error_type']}")
    
    # Review unresolved
    unresolved = service.get_unresolved()
    print(f"\nUnresolved ({len(unresolved)}):")
    for dl in unresolved[:3]:
        print(f"  - {dl.recipient}: {dl.error_type}")
    
    # Mark one resolved
    if unresolved:
        service.mark_resolved(
            unresolved[0].id,
            resolution_notes="Corrected email address and resent"
        )
        print(f"\n✅ Marked {unresolved[0].recipient} as resolved")


async def demo_error_aggregation():
    """Demo: Error aggregation in bulk sends."""
    print("\n" + "="*60)
    print("DEMO 5: Error Aggregation")
    print("="*60)
    
    from unified_sender.engine.error_aggregator import ErrorAggregator
    from unified_sender.exceptions import (
        SMTPConnectionError,
        SMTPMailboxError,
        SMTPRateLimitError
    )
    
    aggregator = ErrorAggregator()
    
    # Simulate bulk send errors
    # 10 connection errors
    for i in range(10):
        aggregator.add_error(
            SMTPConnectionError("Connection timeout"),
            f"user{i}@example.com",
            smtp_server="smtp1.example.com",
            is_transient=True
        )
    
    # 5 mailbox errors
    for i in range(5):
        aggregator.add_error(
            SMTPMailboxError("Mailbox not found"),
            f"invalid{i}@example.com",
            smtp_server="smtp1.example.com",
            is_transient=False
        )
    
    # 2 rate limit errors
    for i in range(2):
        aggregator.add_error(
            SMTPRateLimitError("Too many connections"),
            f"user{i}@example.com",
            smtp_server="smtp2.example.com",
            is_transient=True
        )
    
    # Get summary
    summary = aggregator.get_summary()
    
    print(f"Total errors: {summary.total_errors}")
    print(f"Unique types: {summary.unique_error_types}")
    print(f"Transient: {summary.transient_count}")
    print(f"Permanent: {summary.permanent_count}")
    
    print("\nTop Errors:")
    for i, group in enumerate(summary.groups, 1):
        print(f"  {i}. {group.error_type}: {group.count} occurrences")
        print(f"     Affected {len(group.recipients)} recipients")
    
    print("\nRecommendations:")
    for rec in aggregator.get_recommendations():
        print(f"  💡 {rec}")
    
    if aggregator.has_critical_errors():
        print("\n⚠️  CRITICAL: High permanent error rate detected!")


async def main():
    """Run all demos."""
    # Configure logging
    configure_structured_logging(log_level="INFO")
    
    print("\n🚀 Advanced Error Handling Demo")
    print("Unified Sender v2.0")
    
    await demo_basic_exceptions()
    await demo_circuit_breaker()
    await demo_error_recovery()
    demo_dead_letter_queue()
    await demo_error_aggregation()
    
    print("\n" + "="*60)
    print("✅ All demos completed!")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())


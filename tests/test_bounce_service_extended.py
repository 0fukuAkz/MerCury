import pytest
from mercury.services.bounce_service import BounceService, BounceType, BounceCategory


@pytest.fixture
def bounce_service():
    """Create a BounceService instance."""
    service = BounceService()
    return service


class TestBounceServiceExtended:
    """Extended tests for BounceService."""

    def test_categorize_bounce_hard(self, bounce_service):
        """Test hard bounce categorization."""
        # By pattern
        type_, cat = bounce_service.categorize_bounce(None, "User unknown")
        assert type_ == BounceType.HARD
        assert cat == BounceCategory.INVALID_ADDRESS

        # By code
        type_, cat = bounce_service.categorize_bounce("550", "Something wrong")
        assert type_ == BounceType.HARD
        assert cat == BounceCategory.INVALID_ADDRESS

    def test_categorize_bounce_soft(self, bounce_service):
        """Test soft bounce categorization."""
        # By pattern
        type_, cat = bounce_service.categorize_bounce(None, "Mailbox full")
        assert type_ == BounceType.SOFT
        assert cat == BounceCategory.MAILBOX_FULL

        # By code
        type_, cat = bounce_service.categorize_bounce("421", "Busy")
        assert type_ == BounceType.SOFT
        assert cat == BounceCategory.TECHNICAL

    def test_process_bounce_records(self, bounce_service):
        """Test process_bounce records bounces correctly."""
        bounce_service.process_bounce("hard@test.com", "User unknown")
        assert len(bounce_service._bounces) == 1

        # Soft bounce tracking
        bounce_service.process_bounce("soft@test.com", "Busy")
        assert bounce_service._soft_bounce_counts["soft@test.com"] == 1

    def test_stats(self, bounce_service):
        """Test stats generation."""
        # Force hard bounce with code 550
        bounce_service.process_bounce("hard@test.com", "Error", smtp_code="550")
        bounce_service.process_complaint("spam@test.com")

        stats = bounce_service.get_bounce_stats()
        assert stats["total_bounces"] == 2
        assert stats["hard_bounces"] == 1
        assert stats["complaints"] == 1

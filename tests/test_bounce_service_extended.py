
import pytest
from unittest.mock import Mock, patch, mock_open
from datetime import datetime
from mercury.services.bounce_service import BounceService, BounceType, BounceCategory

@pytest.fixture
def bounce_service():
    """Create a BounceService instance with mocked file."""
    with patch("builtins.open", mock_open(read_data="suppressed@example.com\n")):
        service = BounceService(suppression_file="dummy.txt")
        return service

class TestBounceServiceExtended:
    """Extended tests for BounceService."""

    def test_load_suppression_list(self):
        """Test loading suppression list from file."""
        data = "test@example.com\nother@example.com\n#comment"
        with patch("builtins.open", mock_open(read_data=data)):
            with patch("os.path.exists", return_value=True):
                service = BounceService("dummy.txt")
                assert "test@example.com" in service.get_suppression_list()
                assert "other@example.com" in service.get_suppression_list()
                assert len(service.get_suppression_list()) == 2

    def test_save_suppression_list(self):
        """Test saving suppression list to file."""
        with patch("builtins.open", mock_open()) as mocked_file:
            service = BounceService("dummy.txt")
            service.add_to_suppression_list("new@example.com")
            
            # Should have called write
            mocked_file().write.assert_called()
            # Verify content written includes new email
            # Combine all write calls to check content
            written = "".join(call.args[0] for call in mocked_file().write.call_args_list)
            assert "new@example.com" in written

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

    def test_process_bounce_execution_paths(self, bounce_service):
        """Test process_bounce logic."""
        # Hard bounce logic
        bounce_service.add_to_suppression_list = Mock()
        bounce_service.process_bounce("hard@test.com", "User unknown")
        bounce_service.add_to_suppression_list.assert_called_with("hard@test.com")
        
        # Soft bounce logic - under threshold
        bounce_service.add_to_suppression_list.reset_mock()
        bounce_service.process_bounce("soft@test.com", "Busy")
        bounce_service.add_to_suppression_list.assert_not_called()
        assert bounce_service._soft_bounce_counts["soft@test.com"] == 1
        
        # Soft bounce logic - hit threshold
        # assume threshold is 3
        bounce_service.process_bounce("soft@test.com", "Busy") # 2
        bounce_service.process_bounce("soft@test.com", "Busy") # 3
        bounce_service.add_to_suppression_list.assert_called_with("soft@test.com")

    def test_filter_recipients(self, bounce_service):
        """Test recipient filtering."""
        bounce_service._suppression_list = {"bad@test.com"}
        
        emails = ["good@test.com", "bad@test.com", "good2@test.com"]
        allowed, suppressed = bounce_service.filter_recipients(emails)
        
        assert len(allowed) == 2
        assert "good@test.com" in allowed
        assert "good2@test.com" in allowed
        assert len(suppressed) == 1
        assert "bad@test.com" in suppressed

    def test_import_suppression_list(self):
        """Test importing suppression list."""
        file_content = "import1@test.com\nimport2@test.com"
        
        # Need to mock os.path.exists inside the import method if it verified existence,
        # but the code uses 'open' directly mostly.
        # But wait, we instantiated BounceService("dummy.txt"), which calls load.
        # If we use fixture it's fine.
        
        with patch("builtins.open", mock_open(read_data=file_content)):
            service = BounceService("dummy.txt")
            # Clear initially loaded
            service._suppression_list = set()
            
            # Since mock_open read_data is static, we can reuse context or create new one
            count = service.import_suppression_list("import.txt")
                
            assert count == 2
            assert "import1@test.com" in service._suppression_list
            assert "import2@test.com" in service._suppression_list

    def test_stats(self, bounce_service):
        """Test stats generation."""
        # Force hard bounce with code 550
        bounce_service.process_bounce("hard@test.com", "Error", smtp_code="550")
        bounce_service.process_complaint("spam@test.com")
        
        stats = bounce_service.get_bounce_stats()
        assert stats['total_bounces'] == 2
        assert stats['hard_bounces'] == 1
        assert stats['complaints'] == 1

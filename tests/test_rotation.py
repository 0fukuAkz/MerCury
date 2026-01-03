"""Tests for rotation manager."""

import pytest

from mercury.features.rotation import RotationManager, RotationStrategy


class TestRotationManager:
    """Test rotation manager functionality."""
    
    def test_round_robin_rotation(self):
        """Test round-robin rotation strategy."""
        manager = RotationManager()
        
        items = ["A", "B", "C"]
        manager.register("letters", items, RotationStrategy.ROUND_ROBIN)
        
        # Should cycle through in order
        assert manager.get_next("letters") == "A"
        assert manager.get_next("letters") == "B"
        assert manager.get_next("letters") == "C"
        assert manager.get_next("letters") == "A"  # Back to start
    
    def test_random_rotation(self):
        """Test random rotation strategy."""
        manager = RotationManager()
        
        items = ["A", "B", "C", "D", "E"]
        manager.register("letters", items, RotationStrategy.RANDOM)
        
        # Get several items
        results = [manager.get_next("letters") for _ in range(20)]
        
        # Should have variety (not all the same)
        assert len(set(results)) > 1
        # All should be from original list
        assert all(r in items for r in results)
    
    def test_weighted_rotation(self):
        """Test weighted rotation strategy."""
        manager = RotationManager()
        
        items = ["A", "B", "C"]
        weights = [0.7, 0.2, 0.1]  # A should appear most often
        
        manager.register(
            "letters",
            items,
            RotationStrategy.WEIGHTED,
            weights=weights
        )
        
        # Get many samples
        results = [manager.get_next("letters") for _ in range(1000)]
        
        # A should appear most frequently
        count_a = results.count("A")
        count_b = results.count("B")
        count_c = results.count("C")
        
        assert count_a > count_b
        assert count_b > count_c
    
    def test_get_next_with_fallback(self):
        """Test fallback value when key not registered."""
        manager = RotationManager()
        
        result = manager.get_next("nonexistent", default="default")
        
        assert result == "default"
    
    def test_is_registered(self):
        """Test checking if key is registered."""
        manager = RotationManager()
        
        manager.register("test", ["A", "B"], RotationStrategy.ROUND_ROBIN)
        
        assert manager.is_registered("test") is True
        assert manager.is_registered("other") is False
    
    def test_get_statistics(self):
        """Test getting rotation statistics."""
        manager = RotationManager()
        
        manager.register("items", ["A", "B", "C"], RotationStrategy.ROUND_ROBIN)
        
        # Use the rotation
        manager.get_next("items")
        manager.get_next("items")
        manager.get_next("items")
        
        stats = manager.get_statistics()
        
        assert 'items' in stats
        assert stats['items']['current_index'] == 3
        assert stats['items']['strategy'] == 'round_robin'
    
    def test_register_single_item(self):
        """Test registering single item (no rotation needed)."""
        manager = RotationManager()
        
        manager.register("single", ["Only One"], RotationStrategy.ROUND_ROBIN)
        
        # Should always return the same item
        assert manager.get_next("single") == "Only One"
        assert manager.get_next("single") == "Only One"
    
    def test_empty_items_list(self):
        """Test registering empty list."""
        manager = RotationManager()
        
        manager.register("empty", [], RotationStrategy.ROUND_ROBIN)
        
        # Should return fallback
        result = manager.get_next("empty", default="default")
        assert result == "default"


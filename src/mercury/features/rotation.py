"""Rotation manager for A/B testing and content variation."""

import random
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class RotationStrategy(Enum):
    ROUND_ROBIN = "round_robin"
    WEIGHTED = "weighted"
    RANDOM = "random"
    SEQUENTIAL = "sequential"


@dataclass
class RotationItem:
    """Item in a rotation set."""

    value: Any
    weight: float = 1.0
    count: int = 0
    enabled: bool = True


@dataclass
class RotationSet:
    """Set of items for rotation."""

    name: str
    items: List[RotationItem] = field(default_factory=list)
    strategy: RotationStrategy = RotationStrategy.ROUND_ROBIN
    current_index: int = 0

    def add_item(self, value: Any, weight: float = 1.0) -> "RotationSet":
        """Add item to rotation set."""
        self.items.append(RotationItem(value=value, weight=weight))
        return self

    @property
    def enabled_items(self) -> List[RotationItem]:
        """Get enabled items only."""
        return [item for item in self.items if item.enabled]


class RotationManager:
    """
    Manage rotation of subjects, templates, from names, links, etc.

    Supports multiple rotation strategies:
    - Round Robin: Cycle through items sequentially
    - Weighted: Select based on weight distribution
    - Random: Pure random selection
    - Sequential: Use each item for N sends before moving to next
    """

    def __init__(self):
        self._rotation_sets: Dict[str, RotationSet] = {}
        self._statistics: Dict[str, Dict[str, int]] = {}

    def register(
        self,
        name: str,
        items: List[Any],
        strategy: RotationStrategy = RotationStrategy.ROUND_ROBIN,
        weights: Optional[List[float]] = None,
    ) -> "RotationManager":
        """
        Register a new rotation set.

        Args:
            name: Unique name for this rotation set
            items: List of items to rotate
            strategy: Rotation strategy
            weights: Optional weights for each item

        Returns:
            Self for chaining
        """
        rotation_set = RotationSet(name=name, strategy=strategy)

        for i, item in enumerate(items):
            weight = weights[i] if weights and i < len(weights) else 1.0
            rotation_set.add_item(item, weight)

        self._rotation_sets[name] = rotation_set
        self._statistics[name] = {}

        logger.debug(
            f"Registered rotation '{name}' with {len(items)} items, strategy={strategy.value}"
        )

        return self

    def is_registered(self, name: str) -> bool:
        """Check if rotation set is registered."""
        return name in self._rotation_sets

    def get_next(self, name: str, default: Any = None) -> Any:
        """
        Get next value from rotation set.

        Args:
            name: Rotation set name
            default: Default value if set not found

        Returns:
            Next value from rotation
        """
        if name not in self._rotation_sets:
            return default

        rotation_set = self._rotation_sets[name]
        enabled_items = rotation_set.enabled_items

        if not enabled_items:
            return default

        item = None

        if rotation_set.strategy == RotationStrategy.ROUND_ROBIN:
            item = enabled_items[rotation_set.current_index % len(enabled_items)]
            rotation_set.current_index += 1

        elif rotation_set.strategy == RotationStrategy.WEIGHTED:
            item = self._weighted_selection(enabled_items)

        elif rotation_set.strategy == RotationStrategy.RANDOM:
            item = random.choice(enabled_items)

        elif rotation_set.strategy == RotationStrategy.SEQUENTIAL:
            # Stay on current item until explicitly advanced
            item = enabled_items[rotation_set.current_index % len(enabled_items)]

        if item:
            item.count += 1

            # Track statistics
            value_str = str(item.value)[:50]
            self._statistics[name][value_str] = self._statistics[name].get(value_str, 0) + 1

            return item.value

        return default

    def get_current(self, name: str, default: Any = None) -> Any:
        """Get current value without advancing rotation."""
        if name not in self._rotation_sets:
            return default

        rotation_set = self._rotation_sets[name]
        enabled_items = rotation_set.enabled_items

        if not enabled_items:
            return default

        return enabled_items[rotation_set.current_index % len(enabled_items)].value

    def advance(self, name: str):
        """Manually advance rotation to next item (for SEQUENTIAL strategy)."""
        if name in self._rotation_sets:
            self._rotation_sets[name].current_index += 1

    def reset(self, name: Optional[str] = None):
        """Reset rotation counter(s)."""
        if name:
            if name in self._rotation_sets:
                self._rotation_sets[name].current_index = 0
                for item in self._rotation_sets[name].items:
                    item.count = 0
        else:
            for rotation_set in self._rotation_sets.values():
                rotation_set.current_index = 0
                for item in rotation_set.items:
                    item.count = 0

    def _weighted_selection(self, items: List[RotationItem]) -> Optional[RotationItem]:
        """Select item based on weights."""
        if not items:
            return None

        total_weight = sum(item.weight for item in items)
        if total_weight <= 0:
            return random.choice(items)

        r = random.uniform(0, total_weight)
        cumulative = 0.0

        for item in items:
            cumulative += item.weight
            if r <= cumulative:
                return item

        return items[-1]

    def get_statistics(self, name: Optional[str] = None) -> Dict[str, Any]:
        """
        Get rotation statistics.

        Args:
            name: Specific rotation set name, or None for all

        Returns:
            Statistics dict
        """
        if name:
            if name not in self._rotation_sets:
                return {}

            rotation_set = self._rotation_sets[name]
            return {
                "name": name,
                "strategy": rotation_set.strategy.value,
                "total_items": len(rotation_set.items),
                "enabled_items": len(rotation_set.enabled_items),
                "current_index": rotation_set.current_index,
                "item_counts": {str(item.value)[:50]: item.count for item in rotation_set.items},
                "distribution": self._statistics.get(name, {}),
            }

        return {name: self.get_statistics(name) for name in self._rotation_sets}

    def enable_item(self, name: str, index: int):
        """Enable specific item in rotation."""
        if name in self._rotation_sets and 0 <= index < len(self._rotation_sets[name].items):
            self._rotation_sets[name].items[index].enabled = True

    def disable_item(self, name: str, index: int):
        """Disable specific item in rotation."""
        if name in self._rotation_sets and 0 <= index < len(self._rotation_sets[name].items):
            self._rotation_sets[name].items[index].enabled = False

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "RotationManager":
        """
        Create rotation manager from configuration.

        Config format:
        {
            'subjects': {
                'items': ['Subject 1', 'Subject 2'],
                'strategy': 'round_robin',
                'weights': [0.6, 0.4]
            },
            'templates': {
                'items': ['template1.html', 'template2.html'],
                'strategy': 'weighted'
            }
        }
        """
        manager = cls()

        for name, settings in config.items():
            items = settings.get("items", [])
            strategy_str = settings.get("strategy", "round_robin")
            weights = settings.get("weights")

            try:
                strategy = RotationStrategy(strategy_str)
            except ValueError:
                strategy = RotationStrategy.ROUND_ROBIN
                logger.warning(f"Unknown strategy '{strategy_str}', using round_robin")

            if items:
                manager.register(name, items, strategy, weights)

        return manager

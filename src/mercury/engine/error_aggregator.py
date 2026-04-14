"""Error aggregation for bulk operations."""

from typing import Dict, Any, List, Optional
from datetime import datetime, UTC
from dataclasses import dataclass, field

from ..exceptions import categorize_exception
from ..utils.logging_context import get_context_logger

logger = get_context_logger(__name__)


@dataclass
class ErrorGroup:
    """Group of similar errors."""
    error_type: str
    error_category: str  # smtp_error, validation_error, etc.
    count: int = 0
    recipients: List[str] = field(default_factory=list)
    first_occurrence: Optional[datetime] = None
    last_occurrence: Optional[datetime] = None
    sample_error_message: Optional[str] = None
    smtp_servers: List[str] = field(default_factory=list)
    is_transient: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'error_type': self.error_type,
            'error_category': self.error_category,
            'count': self.count,
            'affected_recipients': len(self.recipients),
            'sample_recipients': self.recipients[:5],  # First 5
            'first_occurrence': self.first_occurrence.isoformat() if self.first_occurrence else None,
            'last_occurrence': self.last_occurrence.isoformat() if self.last_occurrence else None,
            'sample_error': self.sample_error_message,
            'smtp_servers': list(set(self.smtp_servers)),
            'is_transient': self.is_transient
        }


@dataclass
class ErrorSummary:
    """Summary of all errors in a bulk operation."""
    total_errors: int = 0
    unique_error_types: int = 0
    transient_count: int = 0
    permanent_count: int = 0
    groups: List[ErrorGroup] = field(default_factory=list)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'total_errors': self.total_errors,
            'unique_error_types': self.unique_error_types,
            'transient_count': self.transient_count,
            'permanent_count': self.permanent_count,
            'error_groups': [g.to_dict() for g in self.groups],
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'duration_seconds': (
                (self.end_time - self.start_time).total_seconds()
                if self.start_time and self.end_time else 0
            )
        }


class ErrorAggregator:
    """
    Aggregates errors from bulk operations for better insights.
    
    Groups similar errors together to identify patterns and
    systemic issues rather than individual failures.
    """
    
    def __init__(self):
        """Initialize error aggregator."""
        self._groups: Dict[str, ErrorGroup] = {}
        self.start_time = datetime.now(UTC)
    
    def add_error(
        self,
        error: Exception,
        recipient: str,
        smtp_server: Optional[str] = None,
        is_transient: bool = False
    ):
        """
        Add error to aggregation.
        
        Args:
            error: Exception that occurred
            recipient: Email recipient
            smtp_server: SMTP server that failed
            is_transient: Whether error is transient
        """
        error_type = error.__class__.__name__
        error_category = categorize_exception(error)
        
        # Create group key
        group_key = f"{error_category}:{error_type}"
        
        # Get or create group
        if group_key not in self._groups:
            self._groups[group_key] = ErrorGroup(
                error_type=error_type,
                error_category=error_category,
                first_occurrence=datetime.now(UTC),
                sample_error_message=str(error),
                is_transient=is_transient
            )
        
        group = self._groups[group_key]
        group.count += 1
        group.recipients.append(recipient)
        group.last_occurrence = datetime.now(UTC)
        
        if smtp_server and smtp_server not in group.smtp_servers:
            group.smtp_servers.append(smtp_server)
    
    def get_summary(self) -> ErrorSummary:
        """
        Get aggregated error summary.
        
        Returns:
            Error summary with grouped errors
        """
        groups = list(self._groups.values())
        
        transient_count = sum(
            g.count for g in groups if g.is_transient
        )
        permanent_count = sum(
            g.count for g in groups if not g.is_transient
        )
        
        # Sort groups by count (most common first)
        groups.sort(key=lambda g: g.count, reverse=True)
        
        return ErrorSummary(
            total_errors=sum(g.count for g in groups),
            unique_error_types=len(groups),
            transient_count=transient_count,
            permanent_count=permanent_count,
            groups=groups,
            start_time=self.start_time,
            end_time=datetime.now(UTC)
        )
    
    def get_top_errors(self, limit: int = 5) -> List[ErrorGroup]:
        """
        Get most common errors.
        
        Args:
            limit: Number of top errors to return
            
        Returns:
            List of error groups sorted by frequency
        """
        groups = list(self._groups.values())
        groups.sort(key=lambda g: g.count, reverse=True)
        return groups[:limit]
    
    def has_critical_errors(self) -> bool:
        """
        Check if there are critical errors requiring attention.
        
        Returns:
            True if critical errors detected
        """
        # Critical if >50% permanent errors
        total = sum(g.count for g in self._groups.values())
        if total == 0:
            return False
        
        permanent = sum(
            g.count for g in self._groups.values()
            if not g.is_transient
        )
        
        return (permanent / total) > 0.5
    
    def get_recommendations(self) -> List[str]:
        """
        Get recommendations based on error patterns.
        
        Returns:
            List of recommended actions
        """
        recommendations = []
        summary = self.get_summary()
        
        # Check for authentication issues
        auth_errors = [
            g for g in summary.groups
            if 'authentication' in g.error_type.lower()
        ]
        if auth_errors:
            recommendations.append(
                "⚠️  Authentication errors detected - verify SMTP credentials"
            )
        
        # Check for connection issues
        conn_errors = [
            g for g in summary.groups
            if 'connection' in g.error_type.lower()
        ]
        if conn_errors and sum(g.count for g in conn_errors) > 10:
            recommendations.append(
                "🔌 Multiple connection errors - check network or SMTP server status"
            )
        
        # Check for rate limiting
        rate_errors = [
            g for g in summary.groups
            if 'rate' in g.error_type.lower() or 'limit' in g.error_type.lower()
        ]
        if rate_errors:
            recommendations.append(
                "⏱️  Rate limit errors - reduce sending speed or use more SMTP servers"
            )
        
        # Check for mailbox errors
        mailbox_errors = [
            g for g in summary.groups
            if 'mailbox' in g.error_type.lower()
        ]
        if mailbox_errors:
            count = sum(g.count for g in mailbox_errors)
            recommendations.append(
                f"📭 {count} invalid mailbox(es) - clean recipient list"
            )
        
        # High failure rate
        if summary.total_errors > 100:
            recommendations.append(
                f"📊 High error count ({summary.total_errors}) - review configuration"
            )
        
        return recommendations
    
    def log_summary(self):
        """Log error summary to console."""
        summary = self.get_summary()
        
        logger.warning(
            "📋 Error Summary",
            total_errors=summary.total_errors,
            unique_types=summary.unique_error_types,
            transient=summary.transient_count,
            permanent=summary.permanent_count
        )
        
        # Log top errors
        for i, group in enumerate(summary.groups[:5], 1):
            logger.warning(
                f"  #{i}: {group.error_type}",
                count=group.count,
                recipients=len(group.recipients),
                is_transient=group.is_transient
            )
        
        # Log recommendations
        recommendations = self.get_recommendations()
        if recommendations:
            logger.info("💡 Recommendations:")
            for rec in recommendations:
                logger.info(f"  {rec}")
    
    def reset(self):
        """Reset aggregator state."""
        self._groups.clear()
        self._switch_counts.clear()
        self._server_attempts.clear()
        self.start_time = datetime.now(UTC)


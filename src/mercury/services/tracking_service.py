"""Email tracking service for opens, clicks, and engagement metrics."""

import os
import uuid
import logging
import hashlib
from typing import Optional, Dict, Any, List
from datetime import datetime, UTC
from urllib.parse import urlencode
from dataclasses import dataclass, field

from ..security.auth import generate_unsubscribe_token

logger = logging.getLogger(__name__)

# In-memory email_id to recipient mapping (should be moved to database for production)
_email_id_registry: Dict[str, str] = {}


@dataclass
class TrackingEvent:
    """Tracking event record."""
    id: str
    email_id: str
    recipient: str
    event_type: str  # 'open', 'click', 'unsubscribe'
    timestamp: datetime
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    url: Optional[str] = None  # For click events
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'email_id': self.email_id,
            'recipient': self.recipient,
            'event_type': self.event_type,
            'timestamp': self.timestamp.isoformat(),
            'ip_address': self.ip_address,
            'user_agent': self.user_agent,
            'url': self.url,
            'metadata': self.metadata
        }


class TrackingService:
    """
    Service for tracking email opens, clicks, and unsubscribes.
    
    Features:
    - Transparent tracking pixel for opens
    - Link wrapping for click tracking
    - Unsubscribe link generation
    - Event aggregation and statistics
    """
    
    def __init__(self, base_url: Optional[str] = None):
        """Initialize tracking service.

        Resolves ``base_url`` from (1) the explicit argument, then (2) the
        ``TRACKING_BASE_URL`` env var. There is no localhost fallback —
        tracking URLs that point at the wrong host silently break
        production deliveries, so the service raises rather than guess.
        """
        resolved = base_url or os.environ.get('TRACKING_BASE_URL')
        if not resolved:
            raise RuntimeError(
                "TrackingService requires base_url. Pass it explicitly or set "
                "the TRACKING_BASE_URL environment variable (e.g. "
                "https://mail.yourdomain.com)."
            )
        self.base_url = resolved
        self._events: List[TrackingEvent] = []
    
    def generate_email_id(self, recipient: str, campaign_id: Optional[str] = None) -> str:
        """
        Generate unique email ID for tracking.
        
        Args:
            recipient: Recipient email address
            campaign_id: Optional campaign ID
            
        Returns:
            Unique email ID
        """
        # Create deterministic but unique ID
        data = f"{recipient}:{campaign_id or ''}:{datetime.now(UTC).isoformat()}"
        hash_digest = hashlib.sha256(data.encode()).hexdigest()[:16]
        email_id = f"em_{hash_digest}_{uuid.uuid4().hex[:8]}"
        
        # Store mapping for later lookup
        _email_id_registry[email_id] = recipient
        
        return email_id
    
    def get_email_by_id(self, email_id: str) -> Optional[str]:
        """
        Look up recipient email by email_id.
        
        Args:
            email_id: The tracking email ID
            
        Returns:
            Recipient email address or None if not found
        """
        return _email_id_registry.get(email_id)
    
    def generate_tracking_pixel(self, email_id: str) -> str:
        """
        Generate HTML for tracking pixel.
        
        Args:
            email_id: Unique email identifier
            
        Returns:
            HTML img tag for 1x1 transparent pixel
        """
        tracking_url = f"{self.base_url}/track/open/{email_id}"
        return f'<img src="{tracking_url}" width="1" height="1" style="display:none;" alt="" />'
    
    def wrap_link(
        self,
        url: str,
        email_id: str,
        link_id: Optional[str] = None
    ) -> str:
        """
        Wrap URL for click tracking.
        
        Args:
            url: Original URL
            email_id: Email identifier
            link_id: Optional link identifier for A/B testing
            
        Returns:
            Wrapped tracking URL
        """
        # MD5 used purely to derive a short, stable, non-secret link id
        # from the target URL — not for any security property. usedforsecurity=False
        # documents the intent and clears Bandit B324.
        link_id = link_id or hashlib.md5(url.encode(), usedforsecurity=False).hexdigest()[:8]
        params = urlencode({
            'url': url,
            'lid': link_id
        })
        return f"{self.base_url}/track/click/{email_id}?{params}"
    
    def generate_unsubscribe_link(
        self,
        email_id: str,
        recipient: str,
        list_id: Optional[str] = None
    ) -> str:
        """
        Generate one-click unsubscribe link with secure HMAC token.
        
        Args:
            email_id: Email identifier
            recipient: Recipient email (for verification)
            list_id: Optional mailing list ID
            
        Returns:
            Unsubscribe URL with secure token
        """
        # Generate secure HMAC-signed token
        token = generate_unsubscribe_token(
            email=recipient,
            email_id=email_id,
            expires_days=365
        )
        
        return f"{self.base_url}/track/unsubscribe/{email_id}/{token}"
    
    def inject_tracking(
        self,
        html_content: str,
        email_id: str,
        recipient: str,
        track_opens: bool = True,
        track_clicks: bool = True,
        add_unsubscribe: bool = True
    ) -> str:
        """
        Inject tracking elements into HTML email.
        
        Args:
            html_content: Original HTML content
            email_id: Unique email ID
            recipient: Recipient email
            track_opens: Add tracking pixel
            track_clicks: Wrap links for tracking
            add_unsubscribe: Add unsubscribe link
            
        Returns:
            Modified HTML with tracking
        """
        import re
        
        result = html_content
        
        # Track opens: Add pixel before </body>
        if track_opens:
            pixel = self.generate_tracking_pixel(email_id)
            if '</body>' in result.lower():
                result = re.sub(
                    r'</body>',
                    f'{pixel}</body>',
                    result,
                    flags=re.IGNORECASE
                )
            else:
                result += pixel
        
        # Track clicks: Wrap all links
        if track_clicks:
            def replace_link(match):
                full_match = match.group(0)
                url = match.group(1)
                
                # Skip tracking/unsubscribe links
                if '/track/' in url or 'mailto:' in url or '#' in url:
                    return full_match
                
                wrapped = self.wrap_link(url, email_id)
                return full_match.replace(url, wrapped)
            
            # Match href="..." or href='...'
            result = re.sub(
                r'href=["\']([^"\']+)["\']',
                replace_link,
                result
            )
        
        # Add unsubscribe link placeholder
        if add_unsubscribe:
            unsubscribe_url = self.generate_unsubscribe_link(email_id, recipient)
            result = result.replace('{{unsubscribe_link}}', unsubscribe_url)
            result = result.replace('{{unsubscribe_url}}', unsubscribe_url)
        
        return result
    
    def record_event(
        self,
        email_id: str,
        event_type: str,
        recipient: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        url: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> TrackingEvent:
        """
        Record a tracking event.
        
        Args:
            email_id: Email identifier
            event_type: Type of event (open, click, unsubscribe)
            recipient: Recipient email
            ip_address: Client IP address
            user_agent: Client user agent
            url: Clicked URL (for click events)
            metadata: Additional metadata
            
        Returns:
            Created TrackingEvent
        """
        event = TrackingEvent(
            id=str(uuid.uuid4()),
            email_id=email_id,
            recipient=recipient,
            event_type=event_type,
            timestamp=datetime.now(UTC),
            ip_address=ip_address,
            user_agent=user_agent,
            url=url,
            metadata=metadata or {}
        )
        
        self._events.append(event)
        
        logger.info(
            f"Tracking event: {event_type} for {email_id}",
            extra={'event': event.to_dict()}
        )
        
        return event
    
    def get_email_stats(self, email_id: str) -> Dict[str, Any]:
        """Get statistics for a specific email."""
        events = [e for e in self._events if e.email_id == email_id]
        
        opens = [e for e in events if e.event_type == 'open']
        clicks = [e for e in events if e.event_type == 'click']
        
        return {
            'email_id': email_id,
            'opens': len(opens),
            'unique_opens': len(set(e.ip_address for e in opens if e.ip_address)),
            'clicks': len(clicks),
            'unique_clicks': len(set(e.ip_address for e in clicks if e.ip_address)),
            'clicked_urls': list(set(e.url for e in clicks if e.url)),
            'first_open': min((e.timestamp for e in opens), default=None),
            'last_activity': max((e.timestamp for e in events), default=None)
        }
    
    def get_campaign_stats(self, campaign_id: str) -> Dict[str, Any]:
        """Get aggregated statistics for a campaign."""
        # Filter events by campaign (would need campaign_id in metadata)
        events = [
            e for e in self._events 
            if e.metadata.get('campaign_id') == campaign_id
        ]
        
        email_ids = set(e.email_id for e in events)
        opens = [e for e in events if e.event_type == 'open']
        clicks = [e for e in events if e.event_type == 'click']
        unsubscribes = [e for e in events if e.event_type == 'unsubscribe']
        
        return {
            'campaign_id': campaign_id,
            'total_emails': len(email_ids),
            'total_opens': len(opens),
            'unique_opens': len(set(e.email_id for e in opens)),
            'open_rate': len(set(e.email_id for e in opens)) / len(email_ids) * 100 if email_ids else 0,
            'total_clicks': len(clicks),
            'unique_clicks': len(set(e.email_id for e in clicks)),
            'click_rate': len(set(e.email_id for e in clicks)) / len(email_ids) * 100 if email_ids else 0,
            'unsubscribes': len(unsubscribes),
            'unsubscribe_rate': len(unsubscribes) / len(email_ids) * 100 if email_ids else 0
        }


# Transparent 1x1 GIF pixel (base64 encoded)
TRACKING_PIXEL_GIF = (
    b'GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff'
    b'\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00'
    b'\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'
)


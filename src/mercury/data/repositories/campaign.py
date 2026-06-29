"""Campaign repository."""

from typing import Optional, List
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import select

from .base import BaseRepository
from ..models import Campaign, CampaignStatus


class CampaignRepository(BaseRepository[Campaign]):
    """Repository for Campaign entities."""

    def __init__(self, session: Session):
        super().__init__(session, Campaign)

    def get_by_name(self, name: str) -> Optional[Campaign]:
        """Get campaign by name."""
        stmt = select(Campaign).where(Campaign.name == name)
        return self.session.execute(stmt).scalar_one_or_none()

    def get_by_status(self, status: CampaignStatus, limit: int = 100) -> List[Campaign]:
        """Get campaigns by status."""
        stmt = select(Campaign).where(Campaign.status == status).limit(limit)
        return list(self.session.execute(stmt).scalars())

    def get_active(self) -> List[Campaign]:
        """Get all active (sending) campaigns."""
        return self.get_by_status(CampaignStatus.SENDING)

    def get_scheduled(self) -> List[Campaign]:
        """Get all scheduled campaigns."""
        return self.get_by_status(CampaignStatus.SCHEDULED)

    def get(self, id: int) -> Campaign | None:
        """Get campaign by ID with template eagerly loaded."""
        stmt = select(Campaign).where(Campaign.id == id).options(joinedload(Campaign.template))
        return self.session.execute(stmt).scalar_one_or_none()

    def get_recent(self, limit: int = 10) -> List[Campaign]:
        """Get most recent campaigns."""
        stmt = (
            select(Campaign)
            .options(joinedload(Campaign.template))
            .order_by(Campaign.created_at.desc())
            .limit(limit)
        )
        return list(self.session.execute(stmt).scalars())

    def update_status(self, campaign_id: int, status: CampaignStatus) -> Optional[Campaign]:
        """Update campaign status."""
        campaign = self.get(campaign_id)
        if campaign:
            campaign.status = status
            self.session.commit()
        return campaign

    def increment_counters(
        self, campaign_id: int, sent: int = 0, delivered: int = 0, failed: int = 0
    ) -> Optional[Campaign]:
        """Increment campaign counters."""
        campaign = self.get(campaign_id)
        if campaign:
            campaign.sent_count = (campaign.sent_count or 0) + sent
            campaign.delivered_count = (campaign.delivered_count or 0) + delivered
            campaign.failed_count = (campaign.failed_count or 0) + failed
            self.session.commit()
        return campaign

    def search(self, query: str, limit: int = 50) -> List[Campaign]:
        """Search campaigns by name or description."""
        stmt = (
            select(Campaign)
            .where(Campaign.name.ilike(f"%{query}%") | Campaign.description.ilike(f"%{query}%"))
            .limit(limit)
        )
        return list(self.session.execute(stmt).scalars())

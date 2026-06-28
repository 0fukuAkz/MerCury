from typing import List, Dict, Optional, Tuple, Any
from sqlalchemy import func, desc, select
from sqlalchemy.orm import Session

from .base import BaseRepository
from ..models import EmailLog, EmailStatus


class LogRepository(BaseRepository[EmailLog]):
    """Repository for managing email logs."""

    def __init__(self, session: Session):
        super().__init__(session, EmailLog)

    def get_by_campaign(
        self, campaign_id: int, limit: int = 100, offset: int = 0
    ) -> List[EmailLog]:
        """Get logs for a specific campaign."""
        stmt = (
            select(EmailLog)
            .where(EmailLog.campaign_id == campaign_id)
            .order_by(desc(EmailLog.created_at))
            .limit(limit)
            .offset(offset)
        )

        return list(self.session.scalars(stmt).all())

    def get_recent_success(self, limit: int = 100) -> List[EmailLog]:
        """Get recent successful email logs."""
        stmt = (
            select(EmailLog)
            .where(
                EmailLog.status.in_(
                    [
                        EmailStatus.SENT.value,
                        EmailStatus.DELIVERED.value,
                        EmailStatus.OPENED.value,
                        EmailStatus.CLICKED.value,
                    ]
                )
            )
            .order_by(desc(EmailLog.sent_at))
            .limit(limit)
        )

        return list(self.session.scalars(stmt).all())

    def get_recent_failed(self, limit: int = 100) -> List[EmailLog]:
        """Get recent failed email logs."""
        stmt = (
            select(EmailLog)
            .where(EmailLog.status.in_([EmailStatus.FAILED.value, EmailStatus.BOUNCED.value]))
            .order_by(desc(EmailLog.failed_at))
            .limit(limit)
        )

        return list(self.session.scalars(stmt).all())

    def get_last_event_for_recipient(self, email: str) -> Tuple[Optional[str], Optional[str]]:
        """Return (ip, user_agent) from the most-recent open/click for ``email``.

        Used by the campaign send path to backfill geo + UA placeholders
        for recipients whose CSV row doesn't include them. ``(None, None)``
        means "no engagement on file" — caller should fall back to empty
        placeholder values, not raise.

        Searches across ALL campaigns by recipient_email (not scoped to one
        campaign) — a recipient who opened campaign A last week is the same
        person you're sending campaign B to today.
        """
        stmt = (
            select(
                EmailLog.last_event_ip,
                EmailLog.last_event_ua,
            )
            .where(
                EmailLog.recipient_email == email,
                EmailLog.last_event_at.is_not(None),
            )
            .order_by(desc(EmailLog.last_event_at))
            .limit(1)
        )
        row = self.session.execute(stmt).first()
        if row is None:
            return (None, None)
        return (row[0], row[1])

    def get_last_events_bulk(self, emails: List[str]) -> Dict[str, Tuple[str, str]]:
        """Bulk variant of get_last_event_for_recipient.

        Returns ``{email: (ip, ua)}`` for every email that has any engagement
        on file. Emails with no events are simply absent from the result —
        the caller can iterate the input list and treat missing keys as
        "no enrichment available".

        Implemented as one query rather than N: a window function would be
        ideal but isn't portable across SQLite/PostgreSQL old enough to be
        in the wild. Two-pass groupby is good enough for the recipient
        sizes we see (10k-100k per campaign) and avoids the N+1 trap.
        """
        if not emails:
            return {}

        # Most recent timestamp per recipient
        sub = (
            select(
                EmailLog.recipient_email,
                func.max(EmailLog.last_event_at).label("max_ts"),
            )
            .where(
                EmailLog.recipient_email.in_(emails),
                EmailLog.last_event_at.is_not(None),
            )
            .group_by(EmailLog.recipient_email)
            .subquery()
        )

        # Join back to grab the IP/UA at that timestamp
        stmt = select(
            EmailLog.recipient_email,
            EmailLog.last_event_ip,
            EmailLog.last_event_ua,
        ).join(
            sub,
            (EmailLog.recipient_email == sub.c.recipient_email)
            & (EmailLog.last_event_at == sub.c.max_ts),
        )
        out: Dict[str, Tuple[str, str]] = {}
        for email, ip, ua in self.session.execute(stmt).all():
            # Guard against duplicate timestamps (rare; pick first seen).
            out.setdefault(email, (ip or "", ua or ""))
        return out

    def get_global_stats(self) -> Dict[str, Any]:
        """Get global sending statistics efficiently."""

        # We use a single query to group by status and count
        stmt = select(
            EmailLog.status, 
            func.count(EmailLog.id),
            func.sum(EmailLog.open_count),
            func.sum(EmailLog.click_count)
        ).group_by(EmailLog.status)

        results = self.session.execute(stmt).all()
        status_counts = {r[0]: r[1] for r in results}

        total_opens = sum(r[2] or 0 for r in results)
        total_clicks = sum(r[3] or 0 for r in results)

        total_sent = sum(
            status_counts.get(s.value, 0)
            for s in [
                EmailStatus.SENT,
                EmailStatus.DELIVERED,
                EmailStatus.OPENED,
                EmailStatus.CLICKED,
            ]
        )

        total_failed = status_counts.get(EmailStatus.FAILED.value, 0)
        total_bounced = status_counts.get(EmailStatus.BOUNCED.value, 0)

        # Pending/queued/retrying are considered "in progress" or just total attempts
        total_attempts = sum(status_counts.values())

        return {
            "total_sent": total_sent,
            "total_failed": total_failed,
            "total_bounced": total_bounced,
            "total_opens": total_opens,
            "total_clicks": total_clicks,
            "total_attempts": total_attempts,
            "success_rate": round(total_sent / total_attempts * 100, 2)
            if total_attempts > 0
            else 0,
        }

    def get_campaign_engagement_stats(self, campaign_id: int) -> Dict[str, Any]:
        """Compile advanced engagement statistics for a campaign."""
        from sqlalchemy import select, func, case
        from ..models import EmailLog, EmailStatus

        stmt = select(
            func.count(EmailLog.id).label("total"),
            func.sum(case((EmailLog.open_count > 0, 1), else_=0)).label("unique_opens"),
            func.sum(EmailLog.open_count).label("total_opens"),
            func.sum(case((EmailLog.click_count > 0, 1), else_=0)).label("unique_clicks"),
            func.sum(EmailLog.click_count).label("total_clicks"),
            func.sum(case((EmailLog.status == EmailStatus.BOUNCED.value, 1), else_=0)).label(
                "bounces"
            ),
        ).where(EmailLog.campaign_id == campaign_id)

        res = self.session.execute(stmt).first()
        if not res or not res.total:
            return {
                "open_rate": 0.0,
                "click_rate": 0.0,
                "ctr": 0.0,
                "bounces": 0,
                "total_delivered": 0,
                "unique_opens": 0,
                "total_opens": 0,
                "unique_clicks": 0,
                "total_clicks": 0,
            }

        delivered = res.total - (res.bounces or 0)
        unique_opens = res.unique_opens or 0
        unique_clicks = res.unique_clicks or 0

        return {
            "total_delivered": delivered,
            "unique_opens": unique_opens,
            "total_opens": res.total_opens or 0,
            "open_rate": round((unique_opens / delivered * 100), 2) if delivered > 0 else 0.0,
            "unique_clicks": unique_clicks,
            "total_clicks": res.total_clicks or 0,
            "click_rate": round((unique_clicks / delivered * 100), 2) if delivered > 0 else 0.0,
            "ctr": round((unique_clicks / unique_opens * 100), 2) if unique_opens > 0 else 0.0,
            "bounces": res.bounces or 0,
        }

    def get_smtp_performance_stats(self, campaign_id: int) -> List[Dict[str, Any]]:
        """Group delivery metrics by SMTP server with advanced engagement stats."""
        from sqlalchemy import select, func, case
        from ..models import EmailLog, EmailStatus

        stmt = (
            select(
                EmailLog.smtp_server_name,
                func.count(EmailLog.id).label("total"),
                func.sum(
                    case(
                        (
                            EmailLog.status.in_(
                                [
                                    EmailStatus.SENT.value,
                                    EmailStatus.DELIVERED.value,
                                    EmailStatus.OPENED.value,
                                    EmailStatus.CLICKED.value,
                                ]
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ).label("success"),
                func.sum(
                    case(
                        (
                            EmailLog.status.in_(
                                [EmailStatus.FAILED.value, EmailStatus.BOUNCED.value]
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ).label("failed"),
                func.sum(
                    case(
                        (EmailLog.status == EmailStatus.BOUNCED.value, 1),
                        else_=0,
                    )
                ).label("bounces"),
                func.sum(
                    case(
                        (EmailLog.open_count > 0, 1),
                        else_=0,
                    )
                ).label("unique_opens"),
                func.sum(
                    case(
                        (EmailLog.click_count > 0, 1),
                        else_=0,
                    )
                ).label("unique_clicks"),
            )
            .where(EmailLog.campaign_id == campaign_id, EmailLog.smtp_server_name.is_not(None))
            .group_by(EmailLog.smtp_server_name)
        )

        rows = self.session.execute(stmt).all()
        return [
            {
                "smtp_server": r.smtp_server_name,
                "total": r.total,
                "success": r.success or 0,
                "failed": r.failed or 0,
                "bounces": r.bounces or 0,
                "unique_opens": r.unique_opens or 0,
                "unique_clicks": r.unique_clicks or 0,
                "success_rate": round(((r.success or 0) / r.total * 100), 2)
                if r.total > 0
                else 0.0,
                "open_rate": round(((r.unique_opens or 0) / (r.success or 1) * 100), 2)
                if (r.success or 0) > 0
                else 0.0,
                "click_rate": round(((r.unique_clicks or 0) / (r.success or 1) * 100), 2)
                if (r.success or 0) > 0
                else 0.0,
            }
            for r in rows
        ]

    def get_campaign_geo_stats(self, campaign_id: int) -> List[Dict[str, Any]]:
        """Group unique opens by geolocation using the extra_data JSON column if available."""
        from sqlalchemy import select
        from ..models import EmailLog

        # Here we extract country and city from extra_data if possible.
        # This is a bit tricky across DB dialects (SQLite JSON vs Postgres JSONB),
        # so for now we'll do an in-memory aggregation if full JSON operations aren't universally supported,
        # or we just return a stub until the geo enrichment feature is fully implemented.
        # Let's extract all logs for this campaign that have a non-empty extra_data
        stmt = select(EmailLog.extra_data).where(
            EmailLog.campaign_id == campaign_id,
            EmailLog.open_count > 0,
            EmailLog.extra_data.is_not(None),
        )
        rows = self.session.execute(stmt).scalars().all()

        geo_counts: Dict[str, int] = {}
        for data in rows:
            if not isinstance(data, dict):
                continue
            geo = data.get("geo", {})
            country = geo.get("country_name", "Unknown")
            geo_counts[country] = geo_counts.get(country, 0) + 1

        # Convert to list and sort by count descending
        sorted_geo = sorted(
            [{"country": k, "opens": v} for k, v in geo_counts.items()],
            key=lambda x: x["opens"],
            reverse=True,
        )
        return sorted_geo

    def get_campaign_timeline_stats(self, campaign_id: int) -> Dict[str, Any]:
        """Get delivery velocity and engagement events over time."""
        from sqlalchemy import select
        from ..models import EmailLog
        import datetime

        # To remain database-agnostic and handle timezone/formatting uniformly,
        # we'll fetch the relevant timestamps and aggregate in memory.
        # For a single campaign, this is typically a few thousand rows.
        stmt = select(EmailLog.status, EmailLog.updated_at, EmailLog.created_at).where(
            EmailLog.campaign_id == campaign_id
        )
        rows = self.session.execute(stmt).all()

        # Group by minute (YYYY-MM-DD HH:MM)
        timeline: Dict[str, Dict[str, int]] = {}

        for r in rows:
            # Determine the relevant timestamp for the event
            dt = r.updated_at or r.created_at
            if not dt:
                continue

            if isinstance(dt, str):
                try:
                    dt = datetime.datetime.fromisoformat(dt.replace("Z", "+00:00"))
                except ValueError:
                    continue

            time_key = dt.strftime("%Y-%m-%d %H:%M")
            if time_key not in timeline:
                timeline[time_key] = {
                    "sent": 0,
                    "delivered": 0,
                    "failed": 0,
                    "opened": 0,
                    "clicked": 0,
                    "bounced": 0,
                }

            status = r.status
            if status in timeline[time_key]:
                timeline[time_key][status] += 1
            # Treat 'sent' status as sent, but also 'delivered' implies it was sent.
            # We'll just count exactly the current status.

        # Sort by time_key
        sorted_keys = sorted(timeline.keys())

        labels = []
        datasets: dict[str, list[int]] = {
            "sent": [],
            "delivered": [],
            "failed": [],
            "opened": [],
            "clicked": [],
            "bounced": [],
        }

        for key in sorted_keys:
            labels.append(key)
            for metric in datasets.keys():
                datasets[metric].append(timeline[key][metric])

        return {"labels": labels, "datasets": datasets}

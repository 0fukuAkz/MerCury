"""SMTP server repository."""

from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import select

from .base import BaseRepository
from ..models import SMTPServer, SMTPServerStatus


class SMTPRepository(BaseRepository[SMTPServer]):
    """Repository for SMTPServer entities."""

    def __init__(self, session: Session):
        super().__init__(session, SMTPServer)

    def get_by_name(self, name: str) -> Optional[SMTPServer]:
        """Get SMTP server by name."""
        stmt = select(SMTPServer).where(SMTPServer.name == name)
        return self.session.execute(stmt).scalar_one_or_none()

    def get_active(self) -> List[SMTPServer]:
        """Get all active SMTP servers."""
        stmt = (
            select(SMTPServer)
            .where(
                SMTPServer.is_enabled == True,
                SMTPServer.status == SMTPServerStatus.ACTIVE.value,
                SMTPServer.circuit_open == False,
            )
            .order_by(SMTPServer.priority.desc(), SMTPServer.weight.desc())
        )
        return list(self.session.execute(stmt).scalars())

    def get_by_host(self, host: str) -> List[SMTPServer]:
        """Get servers by host."""
        stmt = select(SMTPServer).where(SMTPServer.host == host)
        return list(self.session.execute(stmt).scalars())

    def record_success(self, server_id: int) -> Optional[SMTPServer]:
        """Record successful send."""
        server = self.get(server_id)
        if server:
            server.total_sent += 1
            server.failure_count = 0
            server.circuit_open = False
            self.session.commit()
        return server

    def record_failure(self, server_id: int, error_msg: str = None) -> Optional[SMTPServer]:
        """Record failed send."""
        from datetime import datetime, UTC

        server = self.get(server_id)
        if server:
            server.total_failed += 1
            server.failure_count += 1
            server.last_failure_at = datetime.now(UTC).isoformat()

            # Open circuit breaker after 5 consecutive failures
            if server.failure_count >= 5:
                server.circuit_open = True
                server.status = SMTPServerStatus.ERROR.value

            self.session.commit()
        return server

    def reset_circuit(self, server_id: int) -> Optional[SMTPServer]:
        """Reset circuit breaker for server."""
        server = self.get(server_id)
        if server:
            server.circuit_open = False
            server.failure_count = 0
            server.status = SMTPServerStatus.ACTIVE.value
            self.session.commit()
        return server

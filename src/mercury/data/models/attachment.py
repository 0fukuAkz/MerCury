"""Attachment model.

Represents a reusable file attachment stored on disk. The file payload
lives at ``<data_dir>/attachments/<stored_name>``; only metadata is in
the DB. This split keeps the SQLite file small and lets us swap to S3
later without a schema migration.
"""

from sqlalchemy import Column, String, Integer, Boolean, JSON, Text

from ..database import Base
from .base import BaseModel


class Attachment(Base, BaseModel):
    """Reusable email attachment metadata."""

    __tablename__ = "attachments"

    # User-facing filename — what the recipient sees in the email.
    filename = Column(String(255), nullable=False, index=True)

    # On-disk basename (UUID4 + extension). Never derived from user input,
    # so path traversal is structurally impossible.
    stored_name = Column(String(80), nullable=False, unique=True)

    size_bytes = Column(Integer, nullable=False, default=0)
    content_type = Column(String(120))

    description = Column(Text)
    tags = Column(JSON, default=list)
    is_active = Column(Boolean, default=True, nullable=False)

    def __repr__(self) -> str:
        return f"<Attachment(id={self.id}, filename='{self.filename}')>"

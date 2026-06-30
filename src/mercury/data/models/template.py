"""Email template model."""

from typing import TYPE_CHECKING, Optional, Any
from sqlalchemy import String, Text, Boolean, JSON
from sqlalchemy.orm import Mapped, relationship, mapped_column

from ..database import Base
from .base import BaseModel

if TYPE_CHECKING:
    from .campaign import Campaign


class Template(Base, BaseModel):
    """Email template model."""

    __tablename__ = "templates"

    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text)

    # Content
    html_content: Mapped[Optional[str]] = mapped_column(Text)
    text_content: Mapped[Optional[str]] = mapped_column(Text)
    html_path: Mapped[Optional[str]] = mapped_column(String(500))  # Path to external HTML file

    # Subject templates
    subject: Mapped[Optional[str]] = mapped_column(String(500))
    subject_variants: Mapped[Optional[Any]] = mapped_column(JSON, default=list)

    # Settings
    is_active: Mapped[Optional[bool]] = mapped_column(Boolean, default=True)
    is_default: Mapped[Optional[bool]] = mapped_column(Boolean, default=False)

    # Placeholders used in template
    placeholders_used: Mapped[Optional[Any]] = mapped_column(JSON, default=list)

    # Attachment settings
    attachment_path: Mapped[Optional[str]] = mapped_column(String(500))
    attachment_type: Mapped[Optional[str]] = mapped_column(String(50))  # pdf, docx, html, image

    # Metadata
    tags: Mapped[Optional[Any]] = mapped_column(JSON, default=list)
    settings: Mapped[Optional[Any]] = mapped_column(JSON, default=dict)

    # Relationships
    campaigns: Mapped[list["Campaign"]] = relationship("Campaign", back_populates="template")

    def get_html(self) -> str:
        """Get HTML content from content or file."""
        if self.html_content:
            return self.html_content

        if self.html_path:
            try:
                with open(self.html_path, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception:
                pass

        return ""

    def __repr__(self):
        return f"<Template(id={self.id}, name='{self.name}')>"

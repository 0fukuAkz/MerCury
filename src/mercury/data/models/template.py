"""Email template model."""

from sqlalchemy import Column, String, Text, Boolean, JSON
from sqlalchemy.orm import relationship

from ..database import Base
from .base import BaseModel


class Template(Base, BaseModel):
    """Email template model."""
    
    __tablename__ = 'templates'
    
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text)
    
    # Content
    html_content = Column(Text)
    text_content = Column(Text)
    html_path = Column(String(500))  # Path to external HTML file
    
    # Subject templates
    subject = Column(String(500))
    subject_variants = Column(JSON, default=list)
    
    # Settings
    is_active = Column(Boolean, default=True)
    is_default = Column(Boolean, default=False)
    
    # Placeholders used in template
    placeholders_used = Column(JSON, default=list)
    
    # Attachment settings
    attachment_path = Column(String(500))
    attachment_type = Column(String(50))  # pdf, docx, html, image
    
    # Metadata
    tags = Column(JSON, default=list)
    settings = Column(JSON, default=dict)
    
    # Relationships
    campaigns = relationship("Campaign", back_populates="template")
    
    def get_html(self) -> str:
        """Get HTML content from content or file."""
        if self.html_content:
            return self.html_content
        
        if self.html_path:
            try:
                with open(self.html_path, 'r', encoding='utf-8') as f:
                    return f.read()
            except Exception:
                pass
        
        return ""
    
    def __repr__(self):
        return f"<Template(id={self.id}, name='{self.name}')>"
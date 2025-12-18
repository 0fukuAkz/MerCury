"""Template repository."""

from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import select

from .base import BaseRepository
from ..models import Template


class TemplateRepository(BaseRepository[Template]):
    """Repository for Template entities."""
    
    def __init__(self, session: Session):
        super().__init__(session, Template)
    
    def get_by_name(self, name: str) -> Optional[Template]:
        """Get template by name."""
        stmt = select(Template).where(Template.name == name)
        return self.session.execute(stmt).scalar_one_or_none()
    
    def get_active(self) -> List[Template]:
        """Get all active templates."""
        stmt = (
            select(Template)
            .where(Template.is_active == True)
            .order_by(Template.name)
        )
        return list(self.session.execute(stmt).scalars())
    
    def get_default(self) -> Optional[Template]:
        """Get default template."""
        stmt = (
            select(Template)
            .where(Template.is_default == True, Template.is_active == True)
        )
        return self.session.execute(stmt).scalar_one_or_none()
    
    def set_default(self, template_id: int) -> Optional[Template]:
        """Set template as default."""
        # Clear existing defaults
        for tpl in self.get_active():
            if tpl.is_default:
                tpl.is_default = False
        
        template = self.get(template_id)
        if template:
            template.is_default = True
            self.session.commit()
        return template
    
    def search(self, query: str, limit: int = 50) -> List[Template]:
        """Search templates by name or description."""
        stmt = (
            select(Template)
            .where(
                Template.name.ilike(f'%{query}%') | 
                Template.description.ilike(f'%{query}%')
            )
            .limit(limit)
        )
        return list(self.session.execute(stmt).scalars())


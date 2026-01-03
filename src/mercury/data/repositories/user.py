"""User repository for database operations."""

from typing import Optional, List
from sqlalchemy.orm import Session

from .base import BaseRepository
from ..models.user import User


class UserRepository(BaseRepository[User]):
    """Repository for User model operations."""
    
    def __init__(self, session: Session):
        """
        Initialize user repository.
        
        Args:
            session: SQLAlchemy session
        """
        super().__init__(session, User)
    
    def get_by_username(self, username: str) -> Optional[User]:
        """
        Get user by username.
        
        Args:
            username: Username to search for
            
        Returns:
            User or None if not found
        """
        return self.session.query(User).filter(
            User.username == username
        ).first()
    
    def get_by_email(self, email: str) -> Optional[User]:
        """
        Get user by email.
        
        Args:
            email: Email to search for
            
        Returns:
            User or None if not found
        """
        return self.session.query(User).filter(
            User.email == email
        ).first()
    
    def get_by_api_key(self, api_key: str) -> Optional[User]:
        """
        Get user by API key.
        
        Args:
            api_key: API key to search for
            
        Returns:
            User or None if not found
        """
        return self.session.query(User).filter(
            User.api_key == api_key,
            User.is_active == True
        ).first()
    
    def get_active_users(self) -> List[User]:
        """Get all active users."""
        return self.session.query(User).filter(
            User.is_active == True
        ).all()
    
    def get_admins(self) -> List[User]:
        """Get all admin users."""
        return self.session.query(User).filter(
            User.is_admin == True,
            User.is_active == True
        ).all()
    
    def username_exists(self, username: str) -> bool:
        """Check if username already exists."""
        return self.session.query(User).filter(
            User.username == username
        ).count() > 0
    
    def email_exists(self, email: str) -> bool:
        """Check if email already exists."""
        if not email:
            return False
        return self.session.query(User).filter(
            User.email == email
        ).count() > 0


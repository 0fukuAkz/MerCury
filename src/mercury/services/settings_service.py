"""Service for managing global application settings."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..data.database import get_session_direct
from ..data.models.settings import GlobalSetting

class SettingsService:
    """Service for managing global application settings."""
    
    @staticmethod
    def get_settings() -> GlobalSetting:
        """Get the global settings. Create defaults if not exists."""
        session = get_session_direct()
        try:
            # Singleton: assumption is ID=1 is the only row
            query = select(GlobalSetting).limit(1)
            settings = session.scalar(query)
            
            if not settings:
                # Initialize defaults
                settings = GlobalSetting()
                session.add(settings)
                session.commit()
                session.refresh(settings)
                
            return settings
        finally:
            session.close()

    @staticmethod
    def update_settings(data: dict) -> GlobalSetting:
        """Update global settings."""
        session = get_session_direct()
        try:
            query = select(GlobalSetting).limit(1)
            settings = session.scalar(query)
            
            if not settings:
                settings = GlobalSetting()
                session.add(settings)
            
            # Helper to set attributes if they exist
            for key, value in data.items():
                if hasattr(settings, key):
                     # Type conversion could be added here if needed, 
                     # but Pydantic or form validation should handle it
                    setattr(settings, key, value)
            
            session.commit()
            session.refresh(settings)
            return settings
        finally:
            session.close()

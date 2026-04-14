"""Service for managing sender identities (From Email and Sender Names)."""

import random
from typing import List, Optional
from datetime import datetime, UTC
from sqlalchemy import select
from ..data.database import get_session_direct
from ..data.models.identity import FromEmail, SenderName

class IdentityService:
    """Service for managing sender identities."""
    
    @staticmethod
    def get_emails(active_only: bool = False) -> List[FromEmail]:
        """Get list of From emails."""
        session = get_session_direct()
        try:
            query = select(FromEmail)
            if active_only:
                query = query.where(FromEmail.is_active == True)
            return session.scalars(query).all()
        finally:
            session.close()

    @staticmethod
    def get_names(active_only: bool = False) -> List[SenderName]:
        """Get list of Sender names."""
        session = get_session_direct()
        try:
            query = select(SenderName)
            if active_only:
                query = query.where(SenderName.is_active == True)
            return session.scalars(query).all()
        finally:
            session.close()

    @staticmethod
    def add_email(email: str, tags: list = None) -> FromEmail:
        """Add a new From email."""
        session = get_session_direct()
        try:
            # Check if exists
            existing = session.scalar(select(FromEmail).where(FromEmail.email == email))
            if existing:
                return existing
            
            new_email = FromEmail(email=email, tags=tags or [], is_active=True)
            session.add(new_email)
            session.commit()
            session.refresh(new_email)
            return new_email
        finally:
            session.close()

    @staticmethod
    def add_name(name: str, tags: list = None) -> SenderName:
        """Add a new Sender name."""
        session = get_session_direct()
        try:
            new_name = SenderName(name=name, tags=tags or [], is_active=True)
            session.add(new_name)
            session.commit()
            session.refresh(new_name)
            return new_name
        finally:
            session.close()

    @staticmethod
    def toggle_email_status(email_id: int) -> Optional[FromEmail]:
        """Toggle active status of an email."""
        session = get_session_direct()
        try:
            email = session.get(FromEmail, email_id)
            if email:
                email.is_active = not email.is_active
                session.commit()
                session.refresh(email)
            return email
        finally:
            session.close()

    @staticmethod
    def toggle_name_status(name_id: int) -> Optional[SenderName]:
        """Toggle active status of a name."""
        session = get_session_direct()
        try:
            name = session.get(SenderName, name_id)
            if name:
                name.is_active = not name.is_active
                session.commit()
                session.refresh(name)
            return name
        finally:
            session.close()

    @staticmethod
    def delete_email(email_id: int) -> bool:
        """Delete an email."""
        session = get_session_direct()
        try:
            email = session.get(FromEmail, email_id)
            if email:
                session.delete(email)
                session.commit()
                return True
            return False
        finally:
            session.close()

    @staticmethod
    def delete_name(name_id: int) -> bool:
        """Delete a name."""
        session = get_session_direct()
        try:
            name = session.get(SenderName, name_id)
            if name:
                session.delete(name)
                session.commit()
                return True
            return False
        finally:
            session.close()

    @staticmethod
    def get_random_identity(tag: str = None) -> tuple[Optional[str], Optional[str]]:
        """
        Get a random active email and name.
        Returns: (email, name) tuple. Elements can be None if pools are empty.
        """
        session = get_session_direct()
        try:
            # Get Email
            email_query = select(FromEmail).where(FromEmail.is_active == True)
            # JSON filtering in SQLite can be tricky, doing simplistic check or application-side for now
            # If tags needed, fetching all active and filtering in python for simplicity with SQLite
            all_emails = session.scalars(email_query).all()
            
            selected_email = None
            if all_emails:
                if tag:
                    filtered_emails = [e for e in all_emails if tag in (e.tags or [])]
                    if filtered_emails:
                        selected_email = random.choice(filtered_emails)
                    elif all_emails: # Fallback?
                        selected_email = random.choice(all_emails)
                else:
                    selected_email = random.choice(all_emails)
            
            # Update stats
            if selected_email:
                selected_email.use_count += 1
                selected_email.last_used_at = datetime.now(UTC).isoformat()
                session.add(selected_email)

            # Get Name
            name_query = select(SenderName).where(SenderName.is_active == True)
            all_names = session.scalars(name_query).all()
            
            selected_name = None
            if all_names:
                if tag:
                    filtered_names = [n for n in all_names if tag in (n.tags or [])]
                    if filtered_names:
                        selected_name = random.choice(filtered_names)
                    elif all_names:
                         selected_name = random.choice(all_names)
                else:
                    selected_name = random.choice(all_names)

            if selected_name:
                selected_name.use_count += 1
                selected_name.last_used_at = datetime.now(UTC).isoformat()
                session.add(selected_name)
            
            session.commit()
            
            return (
                selected_email.email if selected_email else None, 
                selected_name.name if selected_name else None
            )
        finally:
            session.close()

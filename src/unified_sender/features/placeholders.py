"""Placeholder processor with 50+ built-in placeholders."""

import os
import re
import uuid
import random
import hashlib
from datetime import datetime, UTC
from typing import Dict, Any, Optional, List, Callable
import logging

logger = logging.getLogger(__name__)

# Try to import Faker for realistic data
try:
    from faker import Faker
    fake = Faker()
    HAS_FAKER = True
except ImportError:
    HAS_FAKER = False
    fake = None


class PlaceholderProcessor:
    """
    Process placeholders in templates with 50+ built-in placeholders.
    
    Placeholder syntax: {{placeholder_name}}
    
    Categories:
    - Recipient: email, domain, local_part, first_name, last_name, etc.
    - Date/Time: date, time, year, month, day, etc.
    - Random: random_name, random_company, random_phone, uuid, etc.
    - Custom: user-defined placeholders
    """
    
    def __init__(self, static_placeholders: Optional[Dict[str, str]] = None):
        """
        Initialize placeholder processor.
        
        Args:
            static_placeholders: Static placeholder values that don't change
        """
        self.static_placeholders = static_placeholders or {}
        self._custom_generators: Dict[str, Callable[[], str]] = {}
        
        # Cache for expensive computations
        self._cache: Dict[str, str] = {}
    
    def register_generator(self, name: str, generator: Callable[[], str]):
        """Register a custom placeholder generator."""
        self._custom_generators[name] = generator
    
    def get_builtin_placeholders(self, recipient_data: Dict[str, Any] = None) -> Dict[str, str]:
        """
        Get all built-in placeholder values.
        
        Args:
            recipient_data: Recipient-specific data
            
        Returns:
            Dict of placeholder name -> value
        """
        recipient_data = recipient_data or {}
        now = datetime.now(UTC)
        
        # Parse email if provided
        email = recipient_data.get('email', '')
        local_part = ''
        domain = ''
        domain_name = ''
        tld = ''
        
        if '@' in email:
            local_part, domain = email.rsplit('@', 1)
            if '.' in domain:
                domain_name = domain.rsplit('.', 1)[0]
                tld = domain.rsplit('.', 1)[1]
            else:
                domain_name = domain
        
        # Generate first/last name from email if not provided
        first_name = recipient_data.get('first_name', '')
        last_name = recipient_data.get('last_name', '')
        
        if not first_name and local_part:
            # Try to extract name from email
            parts = re.split(r'[._\-]', local_part)
            if parts:
                first_name = parts[0].capitalize()
                if len(parts) > 1:
                    last_name = parts[-1].capitalize()
        
        full_name = f"{first_name} {last_name}".strip() or local_part.capitalize()
        
        # Generate unique IDs
        unique_id = str(uuid.uuid4())
        short_id = unique_id[:8]
        
        # Hash of email for consistent random values
        email_hash = hashlib.md5(email.encode()).hexdigest() if email else ''
        
        placeholders = {
            # Recipient info
            'email': email,
            'recipient': email,
            'local_part': local_part,
            'username': local_part,
            'domain': domain,
            'domain_name': domain_name,
            'tld': tld,
            'first_name': first_name,
            'firstname': first_name,
            'last_name': last_name,
            'lastname': last_name,
            'full_name': full_name,
            'fullname': full_name,
            'name': full_name,
            'company': recipient_data.get('company', domain_name.capitalize()),
            
            # Date/Time
            'date': now.strftime('%Y-%m-%d'),
            'date_formatted': now.strftime('%B %d, %Y'),
            'date_short': now.strftime('%m/%d/%Y'),
            'date_eu': now.strftime('%d/%m/%Y'),
            'time': now.strftime('%H:%M:%S'),
            'time_short': now.strftime('%H:%M'),
            'datetime': now.strftime('%Y-%m-%d %H:%M:%S'),
            'timestamp': str(int(now.timestamp())),
            'year': now.strftime('%Y'),
            'month': now.strftime('%m'),
            'month_name': now.strftime('%B'),
            'month_short': now.strftime('%b'),
            'day': now.strftime('%d'),
            'day_name': now.strftime('%A'),
            'day_short': now.strftime('%a'),
            'hour': now.strftime('%H'),
            'minute': now.strftime('%M'),
            'second': now.strftime('%S'),
            'week': now.strftime('%W'),
            'quarter': f"Q{(now.month - 1) // 3 + 1}",
            
            # Unique IDs
            'uuid': unique_id,
            'id': unique_id,
            'short_id': short_id,
            'correlation_id': unique_id,
            'tracking_id': short_id,
            'hash': email_hash[:16],
            
            # Random numbers
            'random_number': str(random.randint(1000, 9999)),
            'random_6': str(random.randint(100000, 999999)),
            'random_8': str(random.randint(10000000, 99999999)),
            
            # Calculated
            'domain_capitalized': domain_name.capitalize() if domain_name else '',
            'email_hash': email_hash,
            'initials': ''.join([n[0].upper() for n in [first_name, last_name] if n]),
        }
        
        # Add Faker-generated placeholders if available
        if HAS_FAKER:
            placeholders.update({
                'random_name': fake.name(),
                'random_first_name': fake.first_name(),
                'random_last_name': fake.last_name(),
                'random_email': fake.email(),
                'random_company': fake.company(),
                'random_phone': fake.phone_number(),
                'random_address': fake.address().replace('\n', ', '),
                'random_city': fake.city(),
                'random_country': fake.country(),
                'random_job': fake.job(),
                'random_text': fake.text(max_nb_chars=100),
                'random_sentence': fake.sentence(),
                'random_word': fake.word(),
                'random_url': fake.url(),
                'random_ip': fake.ipv4(),
                'random_user_agent': fake.user_agent(),
            })
        else:
            # Fallback random data
            names = ['John Smith', 'Jane Doe', 'Bob Wilson', 'Alice Brown']
            companies = ['Acme Inc', 'Global Corp', 'Tech Solutions', 'Innovation Labs']
            placeholders.update({
                'random_name': random.choice(names),
                'random_first_name': random.choice(['John', 'Jane', 'Bob', 'Alice']),
                'random_last_name': random.choice(['Smith', 'Doe', 'Wilson', 'Brown']),
                'random_email': f"user{random.randint(1000,9999)}@example.com",
                'random_company': random.choice(companies),
                'random_phone': f"+1-555-{random.randint(100,999)}-{random.randint(1000,9999)}",
            })
        
        # Add any custom data from recipient
        for key, value in recipient_data.items():
            if key not in placeholders:
                placeholders[key] = str(value) if value is not None else ''
        
        return placeholders
    
    def process(
        self,
        template: str,
        recipient_data: Optional[Dict[str, Any]] = None,
        extra_placeholders: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Process template and replace all placeholders.
        
        Args:
            template: Template string with {{placeholders}}
            recipient_data: Recipient-specific data
            extra_placeholders: Additional placeholder values
            
        Returns:
            Processed string with placeholders replaced
        """
        # Build placeholder dict
        placeholders = self.get_builtin_placeholders(recipient_data)
        placeholders.update(self.static_placeholders)
        
        if extra_placeholders:
            placeholders.update(extra_placeholders)
        
        # Add custom generators
        for name, generator in self._custom_generators.items():
            try:
                placeholders[name] = generator()
            except Exception as e:
                logger.warning(f"Custom generator '{name}' failed: {e}")
                placeholders[name] = ''
        
        # Replace placeholders
        def replace_placeholder(match):
            key = match.group(1).strip()
            return placeholders.get(key, match.group(0))
        
        result = re.sub(r'\{\{([^}]+)\}\}', replace_placeholder, template)
        
        return result
    
    def get_used_placeholders(self, template: str) -> List[str]:
        """Extract list of placeholder names used in template."""
        pattern = r'\{\{([^}]+)\}\}'
        matches = re.findall(pattern, template)
        return [m.strip() for m in matches]
    
    def validate_placeholders(
        self,
        template: str,
        available_placeholders: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Validate that all placeholders in template are available.
        
        Returns:
            Dict with 'valid', 'used', 'missing', 'available'
        """
        used = self.get_used_placeholders(template)
        builtin = set(self.get_builtin_placeholders().keys())
        static = set(self.static_placeholders.keys())
        custom = set(self._custom_generators.keys())
        
        if available_placeholders:
            available = set(available_placeholders) | builtin | static | custom
        else:
            available = builtin | static | custom
        
        missing = [p for p in used if p not in available]
        
        return {
            'valid': len(missing) == 0,
            'used': used,
            'missing': missing,
            'available': list(available)
        }


def generate_identity() -> Dict[str, str]:
    """
    Generate a complete random identity.
    
    Returns:
        Dict with full identity information
    """
    if HAS_FAKER:
        first = fake.first_name()
        last = fake.last_name()
        email_user = f"{first.lower()}.{last.lower()}"
        
        return {
            'first_name': first,
            'last_name': last,
            'full_name': f"{first} {last}",
            'email': f"{email_user}@{fake.domain_name()}",
            'phone': fake.phone_number(),
            'company': fake.company(),
            'job_title': fake.job(),
            'address': fake.address().replace('\n', ', '),
            'city': fake.city(),
            'country': fake.country(),
            'uuid': str(uuid.uuid4())
        }
    else:
        first_names = ['John', 'Jane', 'Michael', 'Sarah', 'David', 'Emily']
        last_names = ['Smith', 'Johnson', 'Williams', 'Brown', 'Jones', 'Davis']
        
        first = random.choice(first_names)
        last = random.choice(last_names)
        
        return {
            'first_name': first,
            'last_name': last,
            'full_name': f"{first} {last}",
            'email': f"{first.lower()}.{last.lower()}@example.com",
            'phone': f"+1-555-{random.randint(100,999)}-{random.randint(1000,9999)}",
            'company': 'Example Corp',
            'job_title': 'Employee',
            'uuid': str(uuid.uuid4())
        }


def apply_placeholders(template: str, placeholders: Dict[str, Any]) -> str:
    """
    Simple placeholder replacement function.
    
    Args:
        template: Template string
        placeholders: Dict of placeholder values
        
    Returns:
        Processed string
    """
    result = template
    for key, value in placeholders.items():
        result = result.replace(f"{{{{{key}}}}}", str(value) if value is not None else '')
    return result


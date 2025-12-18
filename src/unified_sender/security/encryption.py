"""Encryption service for sensitive data like passwords."""

import os
import base64
import logging
from typing import Optional
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)

# Global encryption service instance
_encryption_service: Optional['EncryptionService'] = None


class EncryptionService:
    """
    Service for encrypting and decrypting sensitive data.
    
    Uses Fernet symmetric encryption (AES-128-CBC with HMAC).
    The encryption key is derived from a master password using PBKDF2.
    """
    
    def __init__(self, key: Optional[bytes] = None, password: Optional[str] = None):
        """
        Initialize encryption service.
        
        Args:
            key: Pre-generated Fernet key (32 bytes, base64-encoded)
            password: Master password to derive key from
            
        At least one of key or password must be provided.
        If neither is provided, attempts to load from environment.
        """
        if key:
            self._fernet = Fernet(key)
            self._key = key
        elif password:
            self._key = self._derive_key(password)
            self._fernet = Fernet(self._key)
        else:
            # Try to load from environment
            env_key = os.environ.get('ENCRYPTION_KEY')
            env_password = os.environ.get('ENCRYPTION_PASSWORD')
            
            if env_key:
                self._key = env_key.encode() if isinstance(env_key, str) else env_key
                self._fernet = Fernet(self._key)
            elif env_password:
                self._key = self._derive_key(env_password)
                self._fernet = Fernet(self._key)
            else:
                # Generate a new key and warn
                logger.warning(
                    "No encryption key provided. Generating ephemeral key. "
                    "Set ENCRYPTION_KEY or ENCRYPTION_PASSWORD environment variable for persistence."
                )
                self._key = Fernet.generate_key()
                self._fernet = Fernet(self._key)
    
    @staticmethod
    def _derive_key(password: str, salt: Optional[bytes] = None) -> bytes:
        """
        Derive encryption key from password using PBKDF2.
        
        Args:
            password: Master password
            salt: Optional salt (uses fixed salt if not provided for consistency)
            
        Returns:
            Base64-encoded Fernet key
        """
        # Use a fixed salt derived from environment or a default
        # In production, this should be stored securely
        if salt is None:
            salt_str = os.environ.get('ENCRYPTION_SALT', 'unified-sender-default-salt')
            salt = salt_str.encode()
        
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=480000,  # OWASP recommended minimum
        )
        
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        return key
    
    @staticmethod
    def generate_key() -> bytes:
        """Generate a new random Fernet key."""
        return Fernet.generate_key()
    
    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt a string.
        
        Args:
            plaintext: String to encrypt
            
        Returns:
            Base64-encoded encrypted string
        """
        if not plaintext:
            return plaintext
        
        encrypted = self._fernet.encrypt(plaintext.encode())
        return encrypted.decode()
    
    def decrypt(self, ciphertext: str) -> str:
        """
        Decrypt a string.
        
        Args:
            ciphertext: Base64-encoded encrypted string
            
        Returns:
            Decrypted plaintext string
            
        Raises:
            ValueError: If decryption fails
        """
        if not ciphertext:
            return ciphertext
        
        try:
            decrypted = self._fernet.decrypt(ciphertext.encode())
            return decrypted.decode()
        except InvalidToken as e:
            logger.error("Failed to decrypt: Invalid token or wrong key")
            raise ValueError("Decryption failed: Invalid token or wrong key") from e
    
    def is_encrypted(self, value: str) -> bool:
        """
        Check if a value appears to be encrypted.
        
        Uses heuristic: Fernet tokens are base64 and start with 'gAAAAA'.
        """
        if not value:
            return False
        
        try:
            # Fernet tokens have a specific format
            return value.startswith('gAAAAA') and len(value) > 100
        except Exception:
            return False
    
    def encrypt_if_needed(self, value: str) -> str:
        """Encrypt value only if not already encrypted."""
        if self.is_encrypted(value):
            return value
        return self.encrypt(value)
    
    def decrypt_if_needed(self, value: str) -> str:
        """Decrypt value only if it appears to be encrypted."""
        if not self.is_encrypted(value):
            return value
        return self.decrypt(value)
    
    @property
    def key(self) -> bytes:
        """Get the current encryption key (for backup/storage)."""
        return self._key


def get_encryption_service() -> EncryptionService:
    """Get or create the global encryption service instance."""
    global _encryption_service
    
    if _encryption_service is None:
        _encryption_service = EncryptionService()
    
    return _encryption_service


def set_encryption_service(service: EncryptionService) -> None:
    """Set the global encryption service instance."""
    global _encryption_service
    _encryption_service = service


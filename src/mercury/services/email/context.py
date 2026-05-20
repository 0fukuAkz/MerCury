"""Per-send context shared across the send_single helper pipeline.

Frozen so helpers can't accidentally mutate the placeholders dict (the
caller does the one expected mutation — setting ``placeholders['email']``
— before constructing the context).
"""
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .config import EmailConfig


@dataclass(frozen=True)
class SendContext:
    recipient: str
    placeholders: Dict[str, Any]
    link: Optional[str]
    config: EmailConfig

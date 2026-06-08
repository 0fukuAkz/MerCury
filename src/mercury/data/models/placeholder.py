"""CustomPlaceholder model.

Operator-defined global placeholders. Loaded into PlaceholderProcessor at
campaign-configure time and merged on top of the built-in catalog — see
EmailService.configure() and the precedence rules below.

Precedence (highest wins):
1. Per-recipient CSV columns (e.g. {{first_name}} from the recipient row)
2. Render-time extras ({{link}}, {{qr_code}}, {{company_logo}})
3. **Custom placeholders defined here**
4. Built-in catalog ({{email}}, {{date}}, {{uuid}}, ...)

So custom entries *can* shadow a built-in (operator intent wins over
defaults) but per-recipient data still wins over global custom values.
"""

from sqlalchemy import Boolean, Column, String, Text

from ..database import Base
from .base import BaseModel


class CustomPlaceholder(Base, BaseModel):
    """Global custom placeholder."""

    __tablename__ = "custom_placeholders"

    # Substitution key — `{{<name>}}` in templates. Lowercase + `_` only;
    # the API layer enforces the character set. Unique because two rows
    # with the same name would race-condition resolve and confuse the
    # operator about which value is winning.
    name = Column(String(80), nullable=False, unique=True)

    # The literal text substituted. Stored as Text rather than String
    # because operators sometimes paste multi-line HTML snippets here
    # (e.g. a signature block) and a 255-cap would silently truncate.
    value = Column(Text, nullable=False, default="")

    # Free-form description shown next to the row in the admin UI so the
    # operator who wrote the placeholder six months ago can remember why.
    description = Column(Text)

    # When False, the placeholder is skipped at configure-time — the
    # built-in (if any) wins, or the literal `{{name}}` stays in the
    # rendered email. Useful for temporarily disabling an entry without
    # deleting it.
    is_active = Column(Boolean, default=True, nullable=False)

    def __repr__(self) -> str:
        return f"<CustomPlaceholder(id={self.id}, name='{self.name}')>"

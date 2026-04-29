"""Features layer - Document generators, templates, placeholders."""

from .generators import (
    QRCodeGenerator, 
    PDFGenerator, 
    DOCXGenerator, 
    ImageGenerator,
    AttachmentGenerator,
    GeneratorConfig
)
from .template_engine import TemplateEngine
from .placeholders import PlaceholderProcessor
from .rotation import RotationManager, RotationStrategy
from .encoding import (
    base64_encode_attachment,
    html_entity_encode,
    unicode_homoglyph_replace,
    url_encode_links,
)

__all__ = [
    "QRCodeGenerator",
    "PDFGenerator", 
    "DOCXGenerator",
    "ImageGenerator",
    "AttachmentGenerator",
    "GeneratorConfig",
    "TemplateEngine",
    "PlaceholderProcessor",
    "RotationManager",
    "RotationStrategy",
    "base64_encode_attachment",
    "html_entity_encode",
    "unicode_homoglyph_replace",
    "url_encode_links",
]


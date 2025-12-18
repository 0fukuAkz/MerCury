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
]


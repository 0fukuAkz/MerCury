"""Tests for document generators."""

import pytest
from unified_sender.features.generators import (
    QRCodeGenerator, 
    PDFGenerator, 
    DOCXGenerator,
    ImageGenerator,
    GeneratorConfig
)


def test_qr_code_generator():
    """Test QR code generation."""
    generator = QRCodeGenerator()
    
    data = generator.generate("https://example.com")
    
    assert data is not None
    assert len(data) > 0
    # PNG magic bytes
    assert data[:8] == b'\x89PNG\r\n\x1a\n'


def test_qr_code_data_url():
    """Test QR code as data URL."""
    generator = QRCodeGenerator()
    
    url = generator.generate_data_url("https://example.com")
    
    assert url.startswith("data:image/png;base64,")


def test_pdf_generator():
    """Test PDF generation."""
    generator = PDFGenerator()
    
    html = "<h1>Test PDF</h1><p>This is a test document.</p>"
    data = generator.generate_from_html(html)
    
    assert data is not None
    assert len(data) > 0
    # PDF magic bytes
    assert data[:4] == b'%PDF'


def test_docx_generator():
    """Test DOCX generation."""
    generator = DOCXGenerator()
    
    html = "<h1>Test Document</h1><p>This is a test.</p>"
    data = generator.generate_from_html(html)
    
    assert data is not None
    assert len(data) > 0
    # DOCX is a ZIP file (PK magic bytes)
    assert data[:2] == b'PK'


def test_image_generator():
    """Test image generation."""
    generator = ImageGenerator()
    
    html = "<h1>Test Image</h1><p>This is rendered as an image.</p>"
    data = generator.generate_from_html(html)
    
    assert data is not None
    assert len(data) > 0


def test_custom_qr_colors():
    """Test QR code with custom colors."""
    generator = QRCodeGenerator()
    
    data = generator.generate(
        "https://example.com",
        fill_color="blue",
        back_color="yellow"
    )
    
    assert data is not None
    assert len(data) > 0


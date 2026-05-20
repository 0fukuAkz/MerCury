"""Tests for Document Generators."""

import pytest
from unittest.mock import patch, Mock, MagicMock, mock_open
from mercury.features.generators import (
    QRCodeGenerator, PDFGenerator, DOCXGenerator, 
    ImageGenerator, AttachmentGenerator, GeneratorConfig
)

# --- QRCodeGenerator ---

def test_qr_generator_generate():
    generator = QRCodeGenerator()
    with patch('qrcode.QRCode') as MockQRCode:
        mock_qr = Mock()
        MockQRCode.return_value = mock_qr
        mock_img = Mock()
        mock_qr.make_image.return_value = mock_img
        
        # Mock save to write bytes
        def mock_save(buffer, format):
            buffer.write(b'png-bytes')
        mock_img.save.side_effect = mock_save
        
        result = generator.generate("data")
        assert result == b'png-bytes'
        MockQRCode.assert_called_once()
        mock_qr.add_data.assert_called_with("data")

# --- PDFGenerator ---

def test_pdf_generator_weasyprint():
    config = GeneratorConfig(use_weasyprint=True)
    generator = PDFGenerator(config)
    
    # Mock sys.modules to prevent real weasyprint import
    mock_weasyprint = MagicMock()
    mock_html_class = Mock()
    mock_weasyprint.HTML = mock_html_class
    mock_html_inst = Mock()
    mock_html_class.return_value = mock_html_inst
    mock_html_inst.write_pdf.return_value = b'pdf-bytes'
    
    with patch.dict('sys.modules', {'weasyprint': mock_weasyprint}):
        with patch('mercury.features.generators.PDFGenerator._check_weasyprint', return_value=True):
            generator._weasyprint_available = True
            result = generator.generate_from_html("<html></html>")
            assert result == b'pdf-bytes'
            # Using call_args instead of assert_called_with due to potential kwargs
            assert mock_html_class.called

def test_pdf_generator_reportlab_fallback():
    # Force reportlab path
    config = GeneratorConfig(use_weasyprint=False)
    generator = PDFGenerator(config)
    
    with patch('reportlab.platypus.SimpleDocTemplate') as MockDoc:
        mock_doc = Mock()
        MockDoc.return_value = mock_doc
        
        # Mocking build isn't enough as it writes to buffer passed in init
        # We need to simulate the buffer write that reportlab does
        def mock_build(story):
            # The buffer is the first arg to SimpleDocTemplate
            # But here we mocking only the class
            pass
        mock_doc.build.side_effect = mock_build
        
        # We need to patch BytesIO.getvalue call? 
        # Actually generator creates BytesIO and passes it to SimpleDocTemplate
        # Then calls getvalue().
        # Since SimpleDocTemplate is mocked, it won't write to the buffer.
        # We can mock BytesIO inside the method?
        # Or just assert that it calls build.
        
        # To test return value properly, we should patch io.BytesIO
        with patch('io.BytesIO') as MockBytesIO:
            mock_buffer = Mock()
            MockBytesIO.return_value = mock_buffer
            mock_buffer.getvalue.return_value = b'reportlab-bytes'
            
            result = generator.generate_from_html("<p>Hello</p>")
            
            assert result == b'reportlab-bytes'
            mock_doc.build.assert_called_once()

# --- DOCXGenerator ---

def test_docx_generator_from_html():
    generator = DOCXGenerator()
    
    with patch('docx.Document') as MockDocument, \
         patch('io.BytesIO') as MockBytesIO:
        
        mock_doc = Mock()
        MockDocument.return_value = mock_doc
        mock_doc.paragraphs = []
        
        mock_buffer = Mock()
        MockBytesIO.return_value = mock_buffer
        mock_buffer.getvalue.return_value = b'docx-bytes'
        
        result = generator.generate_from_html("<h1>Title</h1><p>Body</p>")
        
        assert result == b'docx-bytes'
        mock_doc.add_heading.assert_called()
        mock_doc.add_paragraph.assert_called()
        mock_doc.save.assert_called()

def test_docx_generator_template():
    generator = DOCXGenerator()
    
    with patch('docx.Document') as MockDocument, \
         patch('io.BytesIO') as MockBytesIO:
         
        mock_doc = Mock()
        MockDocument.return_value = mock_doc
        
        # Setup paragraphs with placeholders
        p1 = Mock()
        p1.text = "Hello {{name}}"
        mock_doc.paragraphs = [p1]
        mock_doc.tables = []
        
        mock_buffer = Mock()
        MockBytesIO.return_value = mock_buffer
        mock_buffer.getvalue.return_value = b'template-bytes'
        
        result = generator.generate_with_template("path", {'name': 'World'})
        
        assert result == b'template-bytes'
        assert p1.text == "Hello World"
        mock_doc.save.assert_called()

# --- ImageGenerator ---

def test_image_generator():
    # ImageGenerator prefers WeasyPrint+pdf2image and only falls back to the
    # PIL plain-text path when that pipeline fails. We force the fallback by
    # making WeasyPrint raise on import, so the mocks against PIL actually
    # get exercised.
    generator = ImageGenerator()

    with patch.dict('sys.modules', {'weasyprint': None}), \
         patch('PIL.Image.new') as MockNew, \
         patch('PIL.ImageDraw.Draw') as MockDraw, \
         patch('PIL.ImageFont.load_default'):

        mock_img = Mock()
        MockNew.return_value = mock_img

        mock_draw = Mock()
        MockDraw.return_value = mock_draw

        # textbbox returns (x0, y0, x1, y1); small box so it fits the canvas.
        mock_draw.textbbox.return_value = (0, 0, 100, 20)

        def mock_save(buffer, format, quality):
            buffer.write(b'image-bytes')
        mock_img.save.side_effect = mock_save

        result = generator.generate_from_html("<p>Text</p>")

        assert result == b'image-bytes'

# --- AttachmentGenerator ---

def test_attachment_generator():
    gen = AttachmentGenerator()
    
    # Mock internal generators
    gen.pdf.generate_from_html = Mock(return_value=b'pdf')
    gen.qr.generate = Mock(return_value=b'qr')
    gen.docx.generate_from_html = Mock(return_value=b'docx')
    gen.image.generate_from_html = Mock(return_value=b'img')
    
    # Test PDF
    data, name, mime = gen.generate_attachment('pdf', 'content')
    assert data == b'pdf'
    assert mime == 'application/pdf'
    
    # Test QR
    data, name, mime = gen.generate_attachment('qr', 'content')
    assert data == b'qr'
    assert mime == 'image/png'
    
    # Test Invalid
    with pytest.raises(ValueError):
        gen.generate_attachment('invalid', 'c')

def test_generators_data_url_and_file():
    # QRCode
    qr = QRCodeGenerator()
    with patch.object(qr, 'generate', return_value=b'png'):
        assert qr.generate_data_url("d").startswith("data:image/png;base64")
        
        with patch('builtins.open', mock_open()) as m_open:
            qr.generate_to_file("d", "p.png")
            m_open.assert_called()

    # PDF
    pdf = PDFGenerator()
    with patch.object(pdf, 'generate_from_html', return_value=b'pdf'):
        assert pdf.generate_data_url("h").startswith("data:application/pdf;base64")

    # Image
    img = ImageGenerator()
    with patch.object(img, 'generate_from_html', return_value=b'img'):
        assert img.generate_data_url("h", format="PNG").startswith("data:image/png;base64")

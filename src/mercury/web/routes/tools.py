"""Tools route module."""

from flask import Blueprint, render_template, request, send_file, jsonify
from flask_login import login_required
import io

from ...features.generators import AttachmentGenerator, GeneratorConfig

tools_bp = Blueprint('tools', __name__, url_prefix='/tools')

# Lazy-initialized generator to avoid loading WeasyPrint at import time
_generator = None

def _get_generator():
    global _generator
    if _generator is None:
        _generator = AttachmentGenerator(GeneratorConfig())
    return _generator

@tools_bp.route('/')
@login_required
def index():
    """Render tools dashboard."""
    return render_template('tools.html')

@tools_bp.route('/qr', methods=['POST'])
@login_required
def generate_qr():
    """Generate QR code."""
    data = request.form.get('data')
    if not data:
        return jsonify({'error': 'Data is required'}), 400
    
    try:
        qr_bytes = _get_generator().qr.generate(data)
        
        return send_file(
            io.BytesIO(qr_bytes),
            mimetype='image/png',
            as_attachment=True,
            download_name='qrcode.png'
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@tools_bp.route('/render', methods=['POST'])
@login_required
def render_content():
    """Render HTML to PDF or Image."""
    content = request.form.get('content')
    format_type = request.form.get('format', 'pdf') # pdf or image
    
    if not content:
        return jsonify({'error': 'Content is required'}), 400
        
    try:
        if format_type == 'pdf':
            data = _get_generator().pdf.generate_from_html(content)
            mimetype = 'application/pdf'
            filename = 'document.pdf'
        elif format_type == 'image':
            data = _get_generator().image.generate_from_html(content)
            mimetype = 'image/png'
            filename = 'image.png'
        else:
            return jsonify({'error': 'Invalid format'}), 400
            
        return send_file(
            io.BytesIO(data),
            mimetype=mimetype,
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500

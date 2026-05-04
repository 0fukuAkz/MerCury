"""Tests for tools routes."""

import pytest

@pytest.fixture
def logged_in_client(client, admin_user):
    """Log in the test client."""
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_user.id)
        sess['_fresh'] = True
    return client

def test_tools_index(logged_in_client):
    """Test tools dashboard loads."""
    response = logged_in_client.get('/tools/')
    assert response.status_code == 200

def test_generate_qr(logged_in_client):
    """Test QR code generation via web route."""
    response = logged_in_client.post('/tools/qr', data={
        'data': 'https://example.com'
    })
    
    assert response.status_code == 200
    assert response.mimetype == 'image/png'
    # Check if the output is a valid PNG file signature
    assert response.data.startswith(b'\x89PNG\r\n\x1a\n')

def test_generate_qr_missing_data(logged_in_client):
    """Test QR code failure handling."""
    response = logged_in_client.post('/tools/qr', data={})
    assert response.status_code == 400
    assert b'Data is required' in response.data

def test_render_content_pdf(logged_in_client):
    """Test rendering HTML to PDF."""
    html = "<h1>Test Document</h1><p>This is a test.</p>"
    response = logged_in_client.post('/tools/render', data={
        'content': html,
        'format': 'pdf'
    })
    
    assert response.status_code == 200
    assert response.mimetype == 'application/pdf'
    assert response.data.startswith(b'%PDF')

def test_render_content_image(logged_in_client):
    """Test rendering HTML to Image."""
    html = '<div style="background: red; width: 100px; height: 100px;"></div>'
    response = logged_in_client.post('/tools/render', data={
        'content': html,
        'format': 'image'
    })
    
    assert response.status_code == 200
    assert response.mimetype == 'image/png'
    assert response.data.startswith(b'\x89PNG\r\n\x1a\n')

def test_render_content_invalid_format(logged_in_client):
    """Test render fail with bad format. Route now accepts pdf/image/docx —
    use a truly unsupported format to exercise the rejection path."""
    response = logged_in_client.post('/tools/render', data={
        'content': '<b>test</b>',
        'format': 'xyz_unsupported',
    })

    assert response.status_code == 400
    assert b'Invalid format' in response.data

def test_render_content_missing_content(logged_in_client):
    """Test render fail with missing content."""
    response = logged_in_client.post('/tools/render', data={
        'format': 'pdf'
    })
    
    assert response.status_code == 400
    assert b'Content is required' in response.data

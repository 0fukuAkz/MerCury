"""Tests for senders routes."""

import pytest

def test_senders_index(client, admin_user, auth_headers):
    """Test senders dashboard loads."""
    # We need to simulate login or mock IdentityService
    # The route itself doesn't have @login_required, but let's test it
    response = client.get('/senders/')
    assert response.status_code == 200
    assert b'Sender Identities' in response.data or b'Identities' in response.data or b'Senders' in response.data

def test_add_email(client, db_session):
    """Test adding a sender email."""
    # This invokes IdentityService.add_email
    response = client.post('/senders/emails', data={
        'email': 'sender@example.com',
        'tags': 'marketing, sales'
    }, follow_redirects=True)
    
    assert response.status_code == 200
    # IdentityService adds it to DB. We can verify via DB or UI text
    assert b'Email added successfully' in response.data
    
    from mercury.data.models import FromEmail
    identity = db_session.query(FromEmail).filter_by(email='sender@example.com').first()
    assert identity is not None
    assert identity.is_active is True

def test_add_email_validation(client):
    """Test adding email without providing email."""
    response = client.post('/senders/emails', data={
        'email': '',
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert b'Email is required.' in response.data

def test_toggle_email(client, db_session):
    """Test toggling email status."""
    # Setup
    from mercury.data.models import FromEmail
    identity = FromEmail(email='toggle@example.com', is_active=True)
    db_session.add(identity)
    db_session.commit()
    
    response = client.post(f'/senders/emails/{identity.id}/toggle', follow_redirects=True)
    assert response.status_code == 200
    
    db_session.refresh(identity)
    assert identity.is_active is False

def test_delete_email(client, db_session):
    """Test deleting email."""
    from mercury.data.models import FromEmail
    identity = FromEmail(email='delete@example.com', is_active=True)
    db_session.add(identity)
    db_session.commit()
    
    ident_id = identity.id
    response = client.post(f'/senders/emails/{ident_id}/delete', follow_redirects=True)
    assert response.status_code == 200
    assert b'Email deleted.' in response.data
    
    deleted = db_session.query(FromEmail).filter_by(id=ident_id).first()
    assert deleted is None

def test_add_name(client, db_session):
    """Test adding a sender name."""
    response = client.post('/senders/names', data={
        'name': 'Marketing Team',
        'tags': 'marketing'
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert b'Name added successfully' in response.data
    
    from mercury.data.models import SenderName
    identity = db_session.query(SenderName).filter_by(name='Marketing Team').first()
    assert identity is not None

def test_add_name_validation(client):
    """Test adding name without providing name."""
    response = client.post('/senders/names', data={
        'name': '',
    }, follow_redirects=True)
    
    assert response.status_code == 200
    assert b'Name is required.' in response.data

def test_toggle_name(client, db_session):
    """Test toggling name status."""
    from mercury.data.models import SenderName
    identity = SenderName(name='Toggle Name', is_active=True)
    db_session.add(identity)
    db_session.commit()
    
    response = client.post(f'/senders/names/{identity.id}/toggle', follow_redirects=True)
    assert response.status_code == 200
    
    db_session.refresh(identity)
    assert identity.is_active is False

def test_delete_name(client, db_session):
    """Test deleting name."""
    from mercury.data.models import SenderName
    identity = SenderName(name='Delete Name', is_active=True)
    db_session.add(identity)
    db_session.commit()
    
    ident_id = identity.id
    response = client.post(f'/senders/names/{ident_id}/delete', follow_redirects=True)
    assert response.status_code == 200
    assert b'Name deleted.' in response.data
    
    deleted = db_session.query(SenderName).filter_by(id=ident_id).first()
    assert deleted is None

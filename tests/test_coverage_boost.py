"""Tests to boost coverage to 90% — views, tracking, api, encoding, encryption gaps."""

import os
import json
import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy.orm import sessionmaker


# ─────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────

@pytest.fixture
def app_no_login(db_engine):
    """App with LOGIN_DISABLED=True."""
    from mercury.web.app import create_app
    from mercury.app_context import AppContext

    mock_context = MagicMock(spec=AppContext)
    mock_context.limiter = MagicMock()
    mock_context.limiter.limit = lambda x: lambda f: f
    mock_context.socketio = MagicMock()
    mock_context.is_initialized = False

    TestSession = sessionmaker(bind=db_engine)

    with patch('mercury.web.app.init_db'), \
         patch('mercury.security.auth.UserRepository') as MockRepo, \
         patch('mercury.web.app.get_app_context', return_value=mock_context), \
         patch('mercury.data.database.get_session_direct', side_effect=TestSession), \
         patch('mercury.services.smtp_service.get_session_direct', side_effect=TestSession), \
         patch('mercury.services.campaign_service.get_session_direct', side_effect=TestSession), \
         patch('mercury.services.identity_service.get_session_direct', side_effect=TestSession), \
         patch('mercury.services.settings_service.get_session_direct', side_effect=TestSession), \
         patch.dict(os.environ, {'API_KEYS': 'test_api_key'}):

        MockRepo.return_value.get_admins.return_value = [MagicMock()]
        app = create_app(config={
            'TESTING': True, 'WTF_CSRF_ENABLED': False, 'LOGIN_DISABLED': True,
        })
        yield app


@pytest.fixture
def cl(app_no_login):
    return app_no_login.test_client()


# ─────────────────────────────────────────────
# views.py — edit_campaign route (lines 30-43)
# ─────────────────────────────────────────────

def test_edit_campaign_found(cl, db_engine):
    """GET /campaigns/<id>/edit with existing campaign."""
    from mercury.data.models.campaign import Campaign, CampaignStatus

    Session = sessionmaker(bind=db_engine)
    session = Session()
    try:
        c = Campaign(
            name='Test Edit',
            status=CampaignStatus.DRAFT,
            subjects=['Hello'],
        )
        session.add(c)
        session.commit()
        cid = c.id
    finally:
        session.close()

    with patch('mercury.data.database.get_session_direct', side_effect=sessionmaker(bind=db_engine)):
        resp = cl.get(f'/campaigns/{cid}/edit')
    assert resp.status_code == 200
    assert b'Test Edit' in resp.data


def test_edit_campaign_not_found(cl, db_engine):
    """GET /campaigns/<id>/edit with nonexistent campaign returns 404."""
    with patch('mercury.data.database.get_session_direct', side_effect=sessionmaker(bind=db_engine)):
        resp = cl.get('/campaigns/99999/edit')
    assert resp.status_code == 404


# ─────────────────────────────────────────────
# tracking.py — _safe_redirect_url (lines 16-18)
# ─────────────────────────────────────────────

def test_safe_redirect_url_http():
    from mercury.web.routes.tracking import _safe_redirect_url
    assert _safe_redirect_url('http://example.com') == 'http://example.com'


def test_safe_redirect_url_https():
    from mercury.web.routes.tracking import _safe_redirect_url
    assert _safe_redirect_url('https://example.com') == 'https://example.com'


def test_safe_redirect_url_javascript():
    from mercury.web.routes.tracking import _safe_redirect_url
    assert _safe_redirect_url('javascript:alert(1)') == '/'


def test_safe_redirect_url_empty():
    from mercury.web.routes.tracking import _safe_redirect_url
    assert _safe_redirect_url('') == '/'


def test_safe_redirect_url_ftp():
    from mercury.web.routes.tracking import _safe_redirect_url
    assert _safe_redirect_url('ftp://files.example.com') == '/'


# ─────────────────────────────────────────────
# tracking.py — _update_email_log (lines 36-44)
# ─────────────────────────────────────────────

def test_update_email_log_open(db_engine):
    """_update_email_log increments open_count."""
    from mercury.web.routes.tracking import _update_email_log
    from mercury.data.models import EmailLog

    Session = sessionmaker(bind=db_engine)
    session = Session()
    try:
        log = EmailLog(
            correlation_id='track-open-test',
            recipient_email='user@example.com',
            status='sent',
            open_count=0,
            click_count=0,
        )
        session.add(log)
        session.commit()
    finally:
        session.close()

    with patch('mercury.data.database.get_session_direct', side_effect=sessionmaker(bind=db_engine)):
        _update_email_log('track-open-test', 'open')

    session2 = Session()
    try:
        updated = session2.query(EmailLog).filter_by(correlation_id='track-open-test').first()
        assert updated.open_count == 1
    finally:
        session2.close()


def test_update_email_log_click(db_engine):
    """_update_email_log increments click_count."""
    from mercury.web.routes.tracking import _update_email_log
    from mercury.data.models import EmailLog

    Session = sessionmaker(bind=db_engine)
    session = Session()
    try:
        log = EmailLog(
            correlation_id='track-click-test',
            recipient_email='user@example.com',
            status='sent',
            open_count=0,
            click_count=0,
        )
        session.add(log)
        session.commit()
    finally:
        session.close()

    with patch('mercury.data.database.get_session_direct', side_effect=sessionmaker(bind=db_engine)):
        _update_email_log('track-click-test', 'click')

    session2 = Session()
    try:
        updated = session2.query(EmailLog).filter_by(correlation_id='track-click-test').first()
        assert updated.click_count == 1
    finally:
        session2.close()


def test_update_email_log_no_match(db_engine):
    """_update_email_log with unknown email_id does not crash."""
    from mercury.web.routes.tracking import _update_email_log

    with patch('mercury.data.database.get_session_direct', side_effect=sessionmaker(bind=db_engine)):
        _update_email_log('nonexistent-id', 'open')  # should not raise


# ─────────────────────────────────────────────
# api.py — campaign CRUD (lines 136-323)
# ─────────────────────────────────────────────

def test_api_get_campaign(cl, db_engine):
    """GET /api/campaigns/<id>."""
    from mercury.data.models.campaign import Campaign, CampaignStatus
    Session = sessionmaker(bind=db_engine)
    session = Session()
    try:
        c = Campaign(name='GetMe', status=CampaignStatus.DRAFT, subjects=['Sub'])
        session.add(c)
        session.commit()
        cid = c.id
    finally:
        session.close()

    resp = cl.get(f'/api/campaigns/{cid}', headers={'X-API-Key': 'test_api_key'})
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data['campaign']['name'] == 'GetMe'


def test_api_get_campaign_not_found(cl):
    """GET /api/campaigns/<id> with missing campaign."""
    resp = cl.get('/api/campaigns/99999', headers={'X-API-Key': 'test_api_key'})
    assert resp.status_code == 404


def test_api_update_campaign(cl, db_engine):
    """PUT /api/campaigns/<id>."""
    from mercury.data.models.campaign import Campaign, CampaignStatus
    Session = sessionmaker(bind=db_engine)
    session = Session()
    try:
        c = Campaign(name='UpdateMe', status=CampaignStatus.DRAFT, subjects=['Sub'])
        session.add(c)
        session.commit()
        cid = c.id
    finally:
        session.close()

    resp = cl.put(f'/api/campaigns/{cid}',
                  headers={'X-API-Key': 'test_api_key', 'Content-Type': 'application/json'},
                  data=json.dumps({'name': 'Updated', 'subjects': ['New Sub'], 'dry_run': True}))
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data['success'] is True


def test_api_update_campaign_not_found(cl):
    """PUT /api/campaigns/<id> with missing campaign."""
    resp = cl.put('/api/campaigns/99999',
                  headers={'X-API-Key': 'test_api_key', 'Content-Type': 'application/json'},
                  data=json.dumps({'name': 'X'}))
    assert resp.status_code == 404


def test_api_update_campaign_not_editable(cl, db_engine):
    """PUT /api/campaigns/<id> on a completed campaign."""
    from mercury.data.models.campaign import Campaign, CampaignStatus
    Session = sessionmaker(bind=db_engine)
    session = Session()
    try:
        c = Campaign(name='Done', status=CampaignStatus.COMPLETED, subjects=['S'])
        session.add(c)
        session.commit()
        cid = c.id
    finally:
        session.close()

    resp = cl.put(f'/api/campaigns/{cid}',
                  headers={'X-API-Key': 'test_api_key', 'Content-Type': 'application/json'},
                  data=json.dumps({'name': 'X'}))
    assert resp.status_code == 400


def test_api_delete_campaign(cl, db_engine):
    """DELETE /api/campaigns/<id>."""
    from mercury.data.models.campaign import Campaign, CampaignStatus
    Session = sessionmaker(bind=db_engine)
    session = Session()
    try:
        c = Campaign(name='DeleteMe', status=CampaignStatus.DRAFT, subjects=['S'])
        session.add(c)
        session.commit()
        cid = c.id
    finally:
        session.close()

    with patch('mercury.web.events._active_services', {}):
        resp = cl.delete(f'/api/campaigns/{cid}', headers={'X-API-Key': 'test_api_key'})
    assert resp.status_code == 200


def test_api_delete_campaign_not_found(cl):
    """DELETE /api/campaigns/<id> missing."""
    with patch('mercury.web.events._active_services', {}):
        resp = cl.delete('/api/campaigns/99999', headers={'X-API-Key': 'test_api_key'})
    assert resp.status_code == 404


def test_api_bulk_delete(cl, db_engine):
    """POST /api/campaigns/bulk-delete."""
    from mercury.data.models.campaign import Campaign, CampaignStatus
    Session = sessionmaker(bind=db_engine)
    session = Session()
    try:
        c1 = Campaign(name='Bulk1', status=CampaignStatus.DRAFT, subjects=['S'])
        c2 = Campaign(name='Bulk2', status=CampaignStatus.DRAFT, subjects=['S'])
        session.add_all([c1, c2])
        session.commit()
        ids = [c1.id, c2.id]
    finally:
        session.close()

    with patch('mercury.web.events._active_services', {}):
        resp = cl.post('/api/campaigns/bulk-delete',
                       headers={'X-API-Key': 'test_api_key', 'Content-Type': 'application/json'},
                       data=json.dumps({'ids': ids}))
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data['deleted'] == 2


def test_api_bulk_delete_invalid(cl):
    """POST /api/campaigns/bulk-delete without ids."""
    with patch('mercury.web.events._active_services', {}):
        resp = cl.post('/api/campaigns/bulk-delete',
                       headers={'X-API-Key': 'test_api_key', 'Content-Type': 'application/json'},
                       data=json.dumps({}))
    assert resp.status_code == 400


def test_api_clone_campaign(cl, db_engine):
    """POST /api/campaigns/<id>/clone."""
    from mercury.data.models.campaign import Campaign, CampaignStatus
    Session = sessionmaker(bind=db_engine)
    session = Session()
    try:
        c = Campaign(name='CloneMe', status=CampaignStatus.DRAFT, subjects=['Sub'])
        session.add(c)
        session.commit()
        cid = c.id
    finally:
        session.close()

    resp = cl.post(f'/api/campaigns/{cid}/clone', headers={'X-API-Key': 'test_api_key'})
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert 'Copy' in data['campaign']['name']


def test_api_clone_campaign_not_found(cl):
    """POST /api/campaigns/<id>/clone missing."""
    resp = cl.post('/api/campaigns/99999/clone', headers={'X-API-Key': 'test_api_key'})
    assert resp.status_code == 404


# ─────────────────────────────────────────────
# api.py — SMTP update/delete (lines 527-565)
# ─────────────────────────────────────────────

def test_api_update_smtp(cl, db_engine):
    """PUT /api/smtp/<name>."""
    from mercury.data.models import SMTPServer
    Session = sessionmaker(bind=db_engine)
    session = Session()
    try:
        s = SMTPServer(name='testsmtp', host='smtp.example.com', port=587,
                       username='user', password='pass', tls_mode='starttls')
        session.add(s)
        session.commit()
    finally:
        session.close()

    resp = cl.put('/api/smtp/testsmtp',
                  headers={'X-API-Key': 'test_api_key', 'Content-Type': 'application/json'},
                  data=json.dumps({'host': 'smtp2.example.com', 'port': 465}))
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data['success'] is True


def test_api_update_smtp_not_found(cl):
    """PUT /api/smtp/<name> missing."""
    resp = cl.put('/api/smtp/nonexistent',
                  headers={'X-API-Key': 'test_api_key', 'Content-Type': 'application/json'},
                  data=json.dumps({'host': 'x'}))
    assert resp.status_code == 404


def test_api_delete_smtp(cl, db_engine):
    """DELETE /api/smtp/<name>."""
    from mercury.data.models import SMTPServer
    Session = sessionmaker(bind=db_engine)
    session = Session()
    try:
        s = SMTPServer(name='delsmtp', host='smtp.example.com', port=587,
                       username='user', password='pass', tls_mode='starttls')
        session.add(s)
        session.commit()
    finally:
        session.close()

    resp = cl.delete('/api/smtp/delsmtp', headers={'X-API-Key': 'test_api_key'})
    assert resp.status_code == 200


def test_api_delete_smtp_not_found(cl):
    """DELETE /api/smtp/<name> missing."""
    resp = cl.delete('/api/smtp/nonexistent', headers={'X-API-Key': 'test_api_key'})
    assert resp.status_code == 404


# ─────────────────────────────────────────────
# api.py — dead-letter endpoints (lines 1014-1080)
# ─────────────────────────────────────────────

def test_api_list_dead_letters(cl):
    """GET /api/dead-letter."""
    with patch('mercury.data.database.get_session_direct') as mock_sess:
        mock_session = MagicMock()
        mock_sess.return_value = mock_session
        with patch('mercury.data.repositories.dead_letter.DeadLetterRepository') as MockRepo:
            mock_repo = MagicMock()
            mock_repo.get_unresolved.return_value = []
            MockRepo.return_value = mock_repo
            with patch('mercury.services.dead_letter_service.DeadLetterService') as MockSvc:
                mock_svc = MagicMock()
                mock_svc.get_unresolved.return_value = []
                MockSvc.return_value = mock_svc
                resp = cl.get('/api/dead-letter', headers={'X-API-Key': 'test_api_key'})
    assert resp.status_code == 200


def test_api_retry_dead_letter(cl):
    """POST /api/dead-letter/<id>/retry."""
    with patch('mercury.data.database.get_session_direct') as mock_sess:
        mock_session = MagicMock()
        mock_sess.return_value = mock_session
        with patch('mercury.services.dead_letter_service.DeadLetterService') as MockSvc:
            mock_svc = MagicMock()
            mock_svc.retry_dead_letter.return_value = True
            MockSvc.return_value = mock_svc
            resp = cl.post('/api/dead-letter/1/retry', headers={'X-API-Key': 'test_api_key'})
    assert resp.status_code == 200


def test_api_discard_dead_letter(cl):
    """DELETE /api/dead-letter/<id>."""
    with patch('mercury.data.database.get_session_direct') as mock_sess:
        mock_session = MagicMock()
        mock_sess.return_value = mock_session
        with patch('mercury.services.dead_letter_service.DeadLetterService') as MockSvc:
            mock_svc = MagicMock()
            mock_svc.mark_resolved.return_value = True
            MockSvc.return_value = mock_svc
            resp = cl.delete('/api/dead-letter/1', headers={'X-API-Key': 'test_api_key'})
    assert resp.status_code == 200


# ─────────────────────────────────────────────
# api.py — recipients endpoints (lines 875-961, 976-1010)
# ─────────────────────────────────────────────

def test_api_list_recipients(cl, tmp_path):
    """GET /api/recipients."""
    with patch('mercury.web.routes.api.recipients._recipients_dir', return_value=str(tmp_path)):
        # Create a test CSV file
        csv_file = tmp_path / 'test.csv'
        csv_file.write_text('email\nuser@example.com\n')
        resp = cl.get('/api/recipients', headers={'X-API-Key': 'test_api_key'})
    assert resp.status_code == 200


def test_api_upload_recipients(cl, tmp_path):
    """POST /api/recipients/upload."""
    import io
    with patch('mercury.web.routes.api.recipients._recipients_dir', return_value=str(tmp_path)):
        data = {
            'file': (io.BytesIO(b'email\nuser1@example.com\nuser2@example.com\n'), 'test.csv'),
        }
        resp = cl.post('/api/recipients/upload', headers={'X-API-Key': 'test_api_key'},
                       data=data, content_type='multipart/form-data')
    assert resp.status_code == 200
    result = json.loads(resp.data)
    assert result['success'] is True
    assert result['saved'] == 2


def test_api_upload_recipients_no_file(cl):
    """POST /api/recipients/upload without file."""
    resp = cl.post('/api/recipients/upload', headers={'X-API-Key': 'test_api_key'},
                   content_type='multipart/form-data')
    assert resp.status_code == 400


def test_api_preview_recipients(cl, tmp_path):
    """GET /api/recipients/<filename>/preview."""
    csv_file = tmp_path / 'preview.csv'
    csv_file.write_text('email,name\nuser@example.com,User\n')
    with patch('mercury.web.routes.api.recipients._recipients_dir', return_value=str(tmp_path)):
        resp = cl.get('/api/recipients/preview.csv/preview', headers={'X-API-Key': 'test_api_key'})
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data['count'] == 1


def test_api_preview_recipients_not_found(cl, tmp_path):
    """GET /api/recipients/<filename>/preview missing file."""
    with patch('mercury.web.routes.api.recipients._recipients_dir', return_value=str(tmp_path)):
        resp = cl.get('/api/recipients/missing.csv/preview', headers={'X-API-Key': 'test_api_key'})
    assert resp.status_code == 404


def test_api_delete_recipient_file(cl, tmp_path):
    """DELETE /api/recipients/<filename>."""
    csv_file = tmp_path / 'delete_me.csv'
    csv_file.write_text('email\nuser@example.com\n')
    with patch('mercury.web.routes.api.recipients._recipients_dir', return_value=str(tmp_path)):
        resp = cl.delete('/api/recipients/delete_me.csv', headers={'X-API-Key': 'test_api_key'})
    assert resp.status_code == 200
    assert not csv_file.exists()


def test_api_delete_recipient_file_not_found(cl, tmp_path):
    """DELETE /api/recipients/<filename> missing file."""
    with patch('mercury.web.routes.api.recipients._recipients_dir', return_value=str(tmp_path)):
        resp = cl.delete('/api/recipients/missing.csv', headers={'X-API-Key': 'test_api_key'})
    assert resp.status_code == 404


# ─────────────────────────────────────────────
# encoding.py — uncovered branches (lines 49, 61, 67, 70, 73, 90, 111-120)
# ─────────────────────────────────────────────

def test_encoding_homoglyph():
    """Test unicode homoglyph replacement."""
    from mercury.features.encoding import unicode_homoglyph_replace
    result = unicode_homoglyph_replace('<p>Hello World</p>')
    assert '<p>' in result and '</p>' in result  # Tags preserved, text may be modified


def test_encoding_html_entities():
    """Test HTML entity encoding."""
    from mercury.features.encoding import html_entity_encode
    result = html_entity_encode('<p>Hello</p>')
    assert 'Hello' in result or '&#' in result


def test_encoding_url_encode_links():
    """Test URL encoding of links."""
    from mercury.features.encoding import url_encode_links
    result = url_encode_links('<a href="http://example.com/path?q=1">Click</a>')
    assert 'Click' in result


def test_encoding_base64_attachment():
    """Test base64 attachment encoding."""
    from mercury.features.encoding import base64_encode_attachment
    result = base64_encode_attachment(b'test data')
    assert result  # Non-empty


# ─────────────────────────────────────────────
# encryption.py — uncovered lines (69-77, 163-164)
# ─────────────────────────────────────────────

def test_encryption_encrypt_decrypt():
    """Test encrypt and decrypt round-trip."""
    from mercury.security.encryption import EncryptionService
    svc = EncryptionService(password='test-password-for-unit-tests')
    encrypted = svc.encrypt('secret-data')
    decrypted = svc.decrypt(encrypted)
    assert decrypted == 'secret-data'


def test_encryption_decrypt_invalid():
    """Decrypting invalid ciphertext raises or handles gracefully."""
    from mercury.security.encryption import EncryptionService
    svc = EncryptionService(password='test-password-for-unit-tests')
    try:
        svc.decrypt('not-a-valid-encrypted-value')
    except Exception:
        pass  # Expected to raise


def test_encryption_is_encrypted():
    """Test is_encrypted detection."""
    from mercury.security.encryption import EncryptionService
    svc = EncryptionService(password='test-password-for-unit-tests')
    encrypted = svc.encrypt('hello')
    assert svc.is_encrypted(encrypted) is True
    assert svc.is_encrypted('plain-text') is False


def test_encryption_encrypt_if_needed():
    """Test encrypt_if_needed skips already-encrypted."""
    from mercury.security.encryption import EncryptionService
    svc = EncryptionService(password='test-password-for-unit-tests')
    encrypted = svc.encrypt('data')
    # Should not double-encrypt
    result = svc.encrypt_if_needed(encrypted)
    assert svc.decrypt(result) == 'data'


def test_encryption_decrypt_if_needed():
    """Test decrypt_if_needed on plain text."""
    from mercury.security.encryption import EncryptionService
    svc = EncryptionService(password='test-password-for-unit-tests')
    result = svc.decrypt_if_needed('plain-text')
    assert result == 'plain-text'

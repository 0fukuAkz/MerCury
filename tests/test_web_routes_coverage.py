"""Tests for web routes, app, and events to cover missing lines.

Targets gaps not covered by existing test files:
- web/routes/views.py: all render_template lines (require login)
- web/routes/auth.py: successful POST login (lines 30-34), GET /logout (lines 44-46)
- web/app.py: app_context param path (lines 76-77), load_user error (98-100), teardown
- web/events.py: emit_progress (92-93), emit_complete (97-98)
- web/routes/health.py: readiness DB failure (26-27), disk-low branch (95-96)
- web/routes/senders.py: add_email exception branch (30-32), add_name exception (62-64)
- web/routes/settings.py: general exception branch (51-53)
- web/routes/tools.py: generator exception paths (43-44, 74-75)
- web/routes/templates.py: update-not-found, save-exception paths (92-96, 117-121)
- web/routes/api.py: recurring/interval scheduling, bounce list/stats, dead-letter list/retry/discard
"""

import pytest
import json
import os
from unittest.mock import patch, MagicMock
from sqlalchemy.orm import sessionmaker


# ─────────────────────────────────────────────
# Fixture: app with LOGIN_DISABLED for @login_required routes
# ─────────────────────────────────────────────

@pytest.fixture
def app_no_login(db_engine):
    """App fixture with LOGIN_DISABLED=True so @login_required is bypassed."""
    from mercury.web.app import create_app
    from mercury.app_context import AppContext

    mock_context = MagicMock(spec=AppContext)
    mock_context.limiter = MagicMock()
    mock_context.limiter.limit = lambda x: lambda f: f
    mock_context.socketio = MagicMock()
    mock_context.is_initialized = False

    TestSession = sessionmaker(bind=db_engine)

    with patch('mercury.web.app.init_db'), \
         patch('mercury.web.app.UserRepository') as MockRepo, \
         patch('mercury.web.app.get_app_context', return_value=mock_context), \
         patch('mercury.data.database.get_session_direct', side_effect=TestSession), \
         patch('mercury.services.smtp_service.get_session_direct', side_effect=TestSession), \
         patch('mercury.services.campaign_service.get_session_direct', side_effect=TestSession), \
         patch('mercury.web.routes.api.get_session_direct', side_effect=TestSession), \
         patch('mercury.web.routes.templates.get_session_direct', side_effect=TestSession), \
         patch('mercury.web.app.get_session_direct', side_effect=TestSession), \
         patch('mercury.services.identity_service.get_session_direct', side_effect=TestSession), \
         patch('mercury.services.settings_service.get_session_direct', side_effect=TestSession), \
         patch.dict(os.environ, {'API_KEYS': 'test_api_key'}):

        MockRepo.return_value.get_admins.return_value = [MagicMock()]

        app = create_app(config={
            'TESTING': True,
            'WTF_CSRF_ENABLED': False,
            'LOGIN_DISABLED': True,
        })
        yield app


@pytest.fixture
def client_no_login(app_no_login):
    """Test client with LOGIN_DISABLED."""
    return app_no_login.test_client()


@pytest.fixture
def logged_in_client(client, admin_user):
    """Client with a valid Flask-Login session."""
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_user.id)
        sess['_fresh'] = True
    return client


# ─────────────────────────────────────────────
# web/routes/views.py – render_template paths (lines 12,18,24,30,36,42,49,56,63,70)
# ─────────────────────────────────────────────

VIEW_ROUTES = [
    '/',
    '/campaigns',
    '/campaigns/new',
    '/smtp',
    '/logs',
    '/recipients',
    '/scheduling',
    '/bounces',
    '/dead-letter',
    '/webhooks',
]


@pytest.mark.parametrize("route", VIEW_ROUTES)
def test_view_routes_with_login_disabled(client_no_login, route):
    """All view routes render 200 when LOGIN_DISABLED bypasses @login_required."""
    resp = client_no_login.get(route)
    assert resp.status_code == 200


# ─────────────────────────────────────────────
# web/routes/auth.py – POST login success (lines 30-34), GET logout (lines 44-46)
# ─────────────────────────────────────────────

def test_login_post_valid_credentials(client, db_engine):
    """POST /login with correct credentials logs in and redirects (covers lines 30-34)."""
    from mercury.security.auth import hash_password
    from mercury.data.models import User as DBUser

    Session = sessionmaker(bind=db_engine)
    session = Session()
    try:
        u = DBUser(
            username='loginuser',
            email='login@example.com',
            is_admin=False,
            is_active=True,
            must_change_password=False,
        )
        u.password_hash = hash_password('mypassword')
        session.add(u)
        session.commit()
    finally:
        session.close()

    resp = client.post('/login', data={
        'username': 'loginuser',
        'password': 'mypassword',
    }, follow_redirects=False)
    assert resp.status_code in (301, 302)
    # Should redirect away from login on success
    location = resp.headers.get('Location', '')
    assert 'login' not in location.lower()


def test_login_post_with_next_param(client, db_engine):
    """POST /login with ?next= respects next redirect (covers line 34)."""
    from mercury.security.auth import hash_password
    from mercury.data.models import User as DBUser

    Session = sessionmaker(bind=db_engine)
    session = Session()
    try:
        u = DBUser(
            username='nextuser',
            email='next@example.com',
            is_admin=False,
            is_active=True,
            must_change_password=False,
        )
        u.password_hash = hash_password('nextpass')
        session.add(u)
        session.commit()
    finally:
        session.close()

    resp = client.post('/login?next=/campaigns', data={
        'username': 'nextuser',
        'password': 'nextpass',
    }, follow_redirects=False)
    assert resp.status_code in (301, 302)


def test_logout_authenticated(logged_in_client):
    """GET /logout for logged-in user logs out and redirects (covers lines 44-46)."""
    resp = logged_in_client.get('/logout', follow_redirects=False)
    assert resp.status_code in (301, 302)
    location = resp.headers.get('Location', '')
    assert 'login' in location.lower()


# ─────────────────────────────────────────────
# web/app.py – explicit app_context parameter (lines 76-77)
# ─────────────────────────────────────────────

def test_create_app_with_explicit_app_context(db_engine):
    """create_app with app_context= calls set_app_context (covers lines 76-77)."""
    from mercury.web.app import create_app
    from mercury.app_context import AppContext

    mock_context = MagicMock(spec=AppContext)
    mock_context.limiter = MagicMock()
    mock_context.limiter.limit = lambda x: lambda f: f
    mock_context.socketio = MagicMock()
    mock_context.is_initialized = False

    TestSession = sessionmaker(bind=db_engine)

    with patch('mercury.web.app.init_db'), \
         patch('mercury.web.app.UserRepository') as MockRepo, \
         patch('mercury.web.app.set_app_context') as mock_set_ctx, \
         patch('mercury.data.database.get_session_direct', side_effect=TestSession), \
         patch('mercury.web.app.get_session_direct', side_effect=TestSession), \
         patch('mercury.services.smtp_service.get_session_direct', side_effect=TestSession), \
         patch('mercury.services.campaign_service.get_session_direct', side_effect=TestSession), \
         patch('mercury.web.routes.api.get_session_direct', side_effect=TestSession), \
         patch('mercury.web.routes.templates.get_session_direct', side_effect=TestSession), \
         patch('mercury.services.identity_service.get_session_direct', side_effect=TestSession), \
         patch('mercury.services.settings_service.get_session_direct', side_effect=TestSession), \
         patch.dict(os.environ, {'API_KEYS': 'test_api_key'}):

        MockRepo.return_value.get_admins.return_value = [MagicMock()]

        app = create_app(
            config={'TESTING': True, 'WTF_CSRF_ENABLED': False},
            app_context=mock_context,
        )
        mock_set_ctx.assert_called_once_with(mock_context)
        assert app is not None


# ─────────────────────────────────────────────
# web/app.py – load_user exception handler (lines 98-100)
# ─────────────────────────────────────────────

def test_load_user_exception_returns_none(app):
    """load_user swallows exceptions and returns None (covers lines 98-100)."""
    with patch('mercury.web.app.get_user_by_id', side_effect=RuntimeError("DB down")):
        with app.test_request_context('/'):
            login_manager = app.login_manager
            user = login_manager._user_callback('99999')
            assert user is None


# ─────────────────────────────────────────────
# web/app.py – teardown_appcontext (lines 174-175)
# ─────────────────────────────────────────────

def test_teardown_appcontext_fires(app):
    """Entering/exiting an app context exercises teardown hooks (covers lines 174-175)."""
    with app.app_context():
        pass  # teardown callback fires on exit


# ─────────────────────────────────────────────
# web/events.py – emit_progress (lines 92-93) and emit_complete (lines 97-98)
# ─────────────────────────────────────────────

def test_emit_progress_calls_app_context():
    """emit_progress delegates to ctx.emit_progress (covers lines 92-93)."""
    from mercury.web.events import emit_progress

    mock_ctx = MagicMock()
    with patch('mercury.web.events.get_app_context', return_value=mock_ctx):
        emit_progress({'percent': 50, 'sent': 100})

    mock_ctx.emit_progress.assert_called_once_with({'percent': 50, 'sent': 100})


def test_emit_complete_calls_app_context():
    """emit_complete delegates to ctx.emit_complete (covers lines 97-98)."""
    from mercury.web.events import emit_complete

    mock_ctx = MagicMock()
    with patch('mercury.web.events.get_app_context', return_value=mock_ctx):
        emit_complete({'campaign_id': 42, 'status': 'done'})

    mock_ctx.emit_complete.assert_called_once_with({'campaign_id': 42, 'status': 'done'})


# ─────────────────────────────────────────────
# web/routes/health.py – readiness DB failure (lines 26-27), disk-low (95-96)
# ─────────────────────────────────────────────

def test_health_readiness_db_failure(client):
    """GET /ready returns 503 when DB query raises exception (covers lines 26-27)."""
    with patch('mercury.web.routes.health.get_engine') as mock_engine:
        mock_engine.return_value.connect.side_effect = Exception("DB down")
        resp = client.get('/ready')
        assert resp.status_code == 503
        data = json.loads(resp.data)
        assert data['ready'] is False


def test_health_detailed_disk_low(client):
    """Detailed health marks disk as 'warning' when free < 1 GB (covers lines ~95-96)."""
    with patch('shutil.disk_usage', return_value=(100 * 1024**3, 99 * 1024**3, 512 * 1024**2)):
        resp = client.get('/health/detailed')
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data['components']['disk']['status'] == 'warning'
    assert data['status'] == 'degraded'


def test_health_detailed_disk_exception(client):
    """Detailed health handles disk_usage exception (covers disk error branch)."""
    with patch('shutil.disk_usage', side_effect=OSError("No disk")):
        resp = client.get('/health/detailed')
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data['components']['disk']['status'] == 'unknown'


# ─────────────────────────────────────────────
# web/routes/senders.py – exception branches (lines 30-32, 62-64)
# ─────────────────────────────────────────────

def test_senders_add_email_service_exception(client):
    """POST /senders/emails service exception flashes 'Failed to add email' (covers lines 30-32)."""
    with patch('mercury.web.routes.senders.IdentityService.add_email',
               side_effect=Exception("DB error")):
        resp = client.post('/senders/emails', data={
            'email': 'fail@example.com',
        }, follow_redirects=True)
    assert resp.status_code == 200
    assert b'Failed to add email' in resp.data


def test_senders_add_name_service_exception(client):
    """POST /senders/names service exception flashes 'Failed to add name' (covers lines 62-64)."""
    with patch('mercury.web.routes.senders.IdentityService.add_name',
               side_effect=Exception("DB error")):
        resp = client.post('/senders/names', data={
            'name': 'Fail Name',
        }, follow_redirects=True)
    assert resp.status_code == 200
    assert b'Failed to add name' in resp.data


# ─────────────────────────────────────────────
# web/routes/settings.py – general exception branch (lines 51-53)
# ─────────────────────────────────────────────

def test_settings_post_service_exception(client):
    """POST /settings/ general exception flashes 'Failed to update settings' (covers 51-53)."""
    with patch('mercury.web.routes.settings.SettingsService.update_settings',
               side_effect=Exception("DB error")):
        resp = client.post('/settings/', data={
            'daily_limit': '500',
            'hourly_limit': '100',
            'min_delay': '1.0',
            'max_delay': '2.0',
            'default_reply_to': '',
            'max_retries': '3',
            'retry_delay_base': '300',
            'smtp_timeout': '30',
            'max_concurrency': '5',
            'dns_timeout': '5',
            'proxy_enabled': '',
            'proxy_list': '',
            'batch_size': '1000',
            'default_sender_name': '',
            'default_test_email': '',
            'log_retention_days': '30',
            'log_level': 'INFO',
            'ui_theme': 'dark',
        }, follow_redirects=True)
    assert resp.status_code == 200
    assert b'Failed to update settings' in resp.data


# ─────────────────────────────────────────────
# web/routes/tools.py – generator exception paths (lines 43-44, 74-75)
# ─────────────────────────────────────────────

def test_tools_qr_generator_exception(logged_in_client):
    """POST /tools/qr generator exception returns 500 (covers lines 43-44)."""
    mock_qr = MagicMock()
    mock_qr.generate.side_effect = Exception("QR gen failed")

    mock_gen = MagicMock()
    mock_gen.qr = mock_qr

    with patch('mercury.web.routes.tools._get_generator', return_value=mock_gen):
        resp = logged_in_client.post('/tools/qr', data={'data': 'https://example.com'})

    assert resp.status_code == 500
    data = json.loads(resp.data)
    assert 'error' in data


def test_tools_render_pdf_exception(logged_in_client):
    """POST /tools/render pdf exception returns 500 (covers lines 74-75)."""
    mock_pdf = MagicMock()
    mock_pdf.generate_from_html.side_effect = Exception("PDF failed")

    mock_gen = MagicMock()
    mock_gen.pdf = mock_pdf

    with patch('mercury.web.routes.tools._get_generator', return_value=mock_gen):
        resp = logged_in_client.post('/tools/render', data={
            'content': '<h1>Test</h1>',
            'format': 'pdf',
        })

    assert resp.status_code == 500
    data = json.loads(resp.data)
    assert 'error' in data


def test_tools_render_image_exception(logged_in_client):
    """POST /tools/render image exception returns 500 (covers lines 74-75)."""
    mock_image = MagicMock()
    mock_image.generate_from_html.side_effect = Exception("Image failed")

    mock_gen = MagicMock()
    mock_gen.image = mock_image

    with patch('mercury.web.routes.tools._get_generator', return_value=mock_gen):
        resp = logged_in_client.post('/tools/render', data={
            'content': '<h1>Test</h1>',
            'format': 'image',
        })

    assert resp.status_code == 500


# ─────────────────────────────────────────────
# web/routes/templates.py – update-not-found (line 55), exception paths (lines 92-96, 117-121)
# ─────────────────────────────────────────────

def test_templates_save_update_not_found(logged_in_client):
    """POST /templates/save with nonexistent template_id flashes 'Template not found' (covers ~55)."""
    resp = logged_in_client.post('/templates/save', data={
        'template_id': '99999',
        'name': 'Ghost',
        'subject': 'Ghost Subject',
        'html_content': '<p>ghost</p>',
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b'Template not found' in resp.data


def test_templates_save_exception(logged_in_client):
    """POST /templates/save DB exception flashes 'Failed to save template' (covers lines 92-96)."""
    with patch('mercury.web.routes.templates.TemplateRepository') as MockRepo:
        MockRepo.return_value.get_all.return_value = []
        MockRepo.return_value.create = MagicMock(side_effect=Exception("DB error"))
        # Trigger the exception path by making session.add raise
        with patch('mercury.web.routes.templates.get_session_direct') as mock_sess:
            mock_session = MagicMock()
            mock_session.add.side_effect = Exception("DB error")
            mock_session.__enter__ = lambda s: s
            mock_session.__exit__ = MagicMock(return_value=False)
            mock_sess.return_value = mock_session

            resp = logged_in_client.post('/templates/save', data={
                'template_id': '',
                'name': 'Fail Template',
                'subject': 'Fail',
                'html_content': '<p>fail</p>',
            }, follow_redirects=True)
    assert resp.status_code == 200
    assert b'Failed to save template' in resp.data


def test_templates_delete_exception(logged_in_client, db_engine):
    """POST /templates/<id>/delete DB exception flashes 'Failed to delete template' (117-121)."""
    from mercury.data.models import Template

    Session = sessionmaker(bind=db_engine)
    session = Session()
    try:
        t = Template(name='ExceptionMe', subject='X', html_content='<p>x</p>', is_active=True)
        session.add(t)
        session.commit()
        tid = t.id
    finally:
        session.close()

    with patch('mercury.web.routes.templates.TemplateRepository') as MockRepo:
        mock_repo = MagicMock()
        mock_template = MagicMock()
        mock_template.campaigns = []
        mock_repo.get.return_value = mock_template
        mock_repo.delete.side_effect = Exception("DB error")
        MockRepo.return_value = mock_repo

        resp = logged_in_client.post(f'/templates/{tid}/delete', follow_redirects=True)

    assert resp.status_code == 200
    assert b'Failed to delete template' in resp.data


def test_templates_delete_linked_to_campaign(logged_in_client, db_engine):
    """POST /templates/<id>/delete on template with campaigns flashes cannot-delete (117-121)."""
    from mercury.data.models import Template

    Session = sessionmaker(bind=db_engine)
    session = Session()
    try:
        t = Template(name='LinkedTemplate', subject='X', html_content='<p>x</p>', is_active=True)
        session.add(t)
        session.commit()
        tid = t.id
    finally:
        session.close()

    with patch('mercury.web.routes.templates.TemplateRepository') as MockRepo:
        mock_repo = MagicMock()
        mock_template = MagicMock()
        # Simulate template linked to a campaign
        mock_template.campaigns = [MagicMock()]
        mock_repo.get.return_value = mock_template
        MockRepo.return_value = mock_repo

        resp = logged_in_client.post(f'/templates/{tid}/delete', follow_redirects=True)

    assert resp.status_code == 200
    assert b'Cannot delete template linked to campaigns' in resp.data


def test_templates_toggle_exception(logged_in_client, db_engine):
    """POST /templates/<id>/toggle DB exception flashes error (covers lines 117-121)."""
    from mercury.data.models import Template

    Session = sessionmaker(bind=db_engine)
    session = Session()
    try:
        t = Template(name='ToggleException', subject='X', html_content='<p>x</p>', is_active=True)
        session.add(t)
        session.commit()
        tid = t.id
    finally:
        session.close()

    with patch('mercury.web.routes.templates.TemplateRepository') as MockRepo:
        mock_repo = MagicMock()
        mock_template = MagicMock()
        mock_template.is_active = True
        mock_repo.get.return_value = mock_template

        # Make session.commit raise
        with patch('mercury.web.routes.templates.get_session_direct') as mock_sess:
            mock_session = MagicMock()
            mock_session.commit.side_effect = Exception("DB error")
            mock_sess.return_value = mock_session

            resp = logged_in_client.post(f'/templates/{tid}/toggle', follow_redirects=True)

    assert resp.status_code == 200
    assert b'Failed to update template' in resp.data


# ─────────────────────────────────────────────
# web/routes/api.py – scheduling: recurring/interval/invalid/exception
# ─────────────────────────────────────────────

def test_api_create_job_recurring(client, auth_headers):
    """POST /api/scheduling/jobs recurring type (covers lines 354-375)."""
    mock_job = MagicMock()
    mock_job.to_dict.return_value = {'id': 'job-r', 'name': 'Recurring'}

    with patch('mercury.services.scheduler_service.SchedulerService.schedule_recurring',
               return_value=mock_job):
        resp = client.post('/api/scheduling/jobs', headers=auth_headers, json={
            'name': 'Recurring',
            'campaign_id': 1,
            'schedule_type': 'recurring',
            'cron_expression': '0 9 * * *',
        })
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data['success'] is True


def test_api_create_job_recurring_missing_cron(client, auth_headers):
    """POST /api/scheduling/jobs recurring without cron returns 400 (covers lines 354-375)."""
    resp = client.post('/api/scheduling/jobs', headers=auth_headers, json={
        'name': 'Recurring',
        'campaign_id': 1,
        'schedule_type': 'recurring',
    })
    assert resp.status_code == 400
    data = json.loads(resp.data)
    assert 'Cron expression required' in data['error']


def test_api_create_job_interval(client, auth_headers):
    """POST /api/scheduling/jobs interval type (covers lines 354-375)."""
    mock_job = MagicMock()
    mock_job.to_dict.return_value = {'id': 'job-i', 'name': 'Interval'}

    with patch('mercury.services.scheduler_service.SchedulerService.schedule_interval',
               return_value=mock_job):
        resp = client.post('/api/scheduling/jobs', headers=auth_headers, json={
            'name': 'Interval',
            'campaign_id': 1,
            'schedule_type': 'interval',
            'interval_seconds': 3600,
        })
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data['success'] is True


def test_api_create_job_interval_missing_seconds(client, auth_headers):
    """POST /api/scheduling/jobs interval without interval_seconds returns 400."""
    resp = client.post('/api/scheduling/jobs', headers=auth_headers, json={
        'name': 'Interval',
        'campaign_id': 1,
        'schedule_type': 'interval',
    })
    assert resp.status_code == 400
    data = json.loads(resp.data)
    assert 'Interval seconds required' in data['error']


def test_api_create_job_invalid_schedule_type(client, auth_headers):
    """POST /api/scheduling/jobs unknown schedule_type returns 400 (covers lines 381-382)."""
    resp = client.post('/api/scheduling/jobs', headers=auth_headers, json={
        'name': 'Bad Type',
        'campaign_id': 1,
        'schedule_type': 'unknown_type',
    })
    assert resp.status_code == 400
    data = json.loads(resp.data)
    assert 'Invalid schedule type' in data['error']


def test_api_create_job_service_exception(client, auth_headers):
    """POST /api/scheduling/jobs service exception returns 500 (covers lines 403-408)."""
    with patch('mercury.services.scheduler_service.SchedulerService.schedule_once',
               side_effect=Exception("Scheduler error")):
        resp = client.post('/api/scheduling/jobs', headers=auth_headers, json={
            'name': 'Fail Job',
            'campaign_id': 1,
            'schedule_type': 'once',
            'run_at': '2030-01-01T12:00:00',
        })
    assert resp.status_code == 500
    data = json.loads(resp.data)
    assert 'error' in data


def test_api_pause_job(client, auth_headers):
    """POST /api/scheduling/jobs/<id>/pause pauses job (covers lines 431-437)."""
    with patch('mercury.services.scheduler_service.SchedulerService.pause_job'):
        resp = client.post('/api/scheduling/jobs/job-1/pause', headers=auth_headers)
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data['success'] is True


def test_api_resume_job(client, auth_headers):
    """POST /api/scheduling/jobs/<id>/resume resumes job (covers lines 447-452)."""
    with patch('mercury.services.scheduler_service.SchedulerService.resume_job'):
        resp = client.post('/api/scheduling/jobs/job-1/resume', headers=auth_headers)
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data['success'] is True


# ─────────────────────────────────────────────
# web/routes/api.py – bounce list and stats (lines 482, 510-524)
# ─────────────────────────────────────────────

def test_api_list_bounces(client, auth_headers):
    """GET /api/bounces returns bounce list (covers line 482)."""
    resp = client.get('/api/bounces', headers=auth_headers)
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert 'bounces' in data


def test_api_bounce_stats(client, auth_headers):
    """GET /api/bounces/stats returns statistics (covers lines 510-524)."""
    with patch('mercury.services.bounce_service.BounceService.get_bounce_stats',
               return_value={'total': 0, 'hard': 0, 'soft': 0}):
        resp = client.get('/api/bounces/stats', headers=auth_headers)
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert 'total' in data


def test_api_add_to_suppression_missing_email(client, auth_headers):
    """POST /api/bounces/suppression without email returns 400 (covers lines 551-562)."""
    resp = client.post('/api/bounces/suppression', headers=auth_headers, json={})
    assert resp.status_code == 400
    data = json.loads(resp.data)
    assert 'Email is required' in data['error']


# ─────────────────────────────────────────────
# web/routes/api.py – dead-letter list, retry, discard (lines 510-524, 532-543, 551-562)
# ─────────────────────────────────────────────

def test_api_list_dead_letters(client, auth_headers):
    """GET /api/dead-letter returns items list."""
    mock_item = MagicMock()
    mock_item.to_dict.return_value = {'id': 1, 'recipient': 'test@example.com'}

    with patch('mercury.services.dead_letter_service.DeadLetterService.get_unresolved',
               return_value=[mock_item]):
        resp = client.get('/api/dead-letter', headers=auth_headers)
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert 'items' in data
    assert data['count'] == 1


def test_api_retry_dead_letter(client, auth_headers):
    """POST /api/dead-letter/<id>/retry retries the item."""
    mock_result = MagicMock()

    with patch('mercury.services.dead_letter_service.DeadLetterService.retry_dead_letter',
               return_value=mock_result):
        resp = client.post('/api/dead-letter/1/retry', headers=auth_headers)
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data['success'] is True


def test_api_retry_dead_letter_not_found(client, auth_headers):
    """POST /api/dead-letter/<id>/retry returns success=False when not found."""
    with patch('mercury.services.dead_letter_service.DeadLetterService.retry_dead_letter',
               return_value=None):
        resp = client.post('/api/dead-letter/99999/retry', headers=auth_headers)
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data['success'] is False


def test_api_discard_dead_letter(client, auth_headers):
    """DELETE /api/dead-letter/<id> discards item."""
    mock_result = MagicMock()

    with patch('mercury.services.dead_letter_service.DeadLetterService.mark_resolved',
               return_value=mock_result):
        resp = client.delete('/api/dead-letter/1', headers=auth_headers)
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data['success'] is True


def test_api_discard_dead_letter_not_found(client, auth_headers):
    """DELETE /api/dead-letter/<id> returns success=False when not found."""
    with patch('mercury.services.dead_letter_service.DeadLetterService.mark_resolved',
               return_value=None):
        resp = client.delete('/api/dead-letter/99999', headers=auth_headers)
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data['success'] is False

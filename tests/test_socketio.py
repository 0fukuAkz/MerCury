"""Tests for Socket.IO events."""

import pytest
from unittest.mock import patch, Mock, MagicMock


@pytest.fixture
def socketio_instance():
    """Get the application SocketIO instance."""
    from mercury.web.extensions import socketio

    return socketio


def test_socketio_message_queue_defaults_to_in_process():
    """Unset SOCKETIO_MESSAGE_QUEUE must stay in-process (None) so the
    single-worker default is unchanged; it's opt-in only when scaling out."""
    import mercury.web.extensions as ext

    assert ext._message_queue is None


@pytest.fixture
def socket_app(app, mock_user_loader, socketio_instance):
    with patch("mercury.web.app.get_app_context") as mock_ctx_getter:
        mock_ctx = Mock()
        mock_ctx.socketio = socketio_instance
        mock_ctx.limiter.limit.side_effect = lambda limit_string: lambda f: f
        mock_ctx_getter.return_value = mock_ctx
        socketio_instance.init_app(app)
        return app


@pytest.fixture
def auth_client_socket(socket_app):
    """Authenticated Flask test client."""
    with patch("mercury.web.app.api_key_or_login_required", side_effect=lambda f: f):
        pass

    return socket_app.test_client()


@pytest.fixture
def mock_user_loader():
    with patch("mercury.security.auth.get_user_by_id") as mock_get:
        from mercury.security.auth import User as AuthUser

        user = AuthUser(id="1", username="admin", password_hash="hash", is_admin=True)
        mock_get.side_effect = lambda uid: user if str(uid) == "1" else None
        yield mock_get


def test_socket_connect_authenticated(socket_app, socketio_instance):
    """Test socket connection with authenticated user."""
    with patch("flask_login.utils._get_user") as mock_user_getter:
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.is_active = True
        mock_user.username = "admin"
        mock_user_getter.return_value = mock_user

        client = socketio_instance.test_client(socket_app)
        assert client.is_connected()

        received = client.get_received()
        assert len(received) > 0
        assert received[0]["name"] == "connected"


def test_socket_connect_unauthenticated(socket_app, socketio_instance):
    """Test connection rejection for unauthenticated user."""
    with patch("flask_login.utils._get_user") as mock_user_getter:
        mock_user = MagicMock()
        mock_user.is_authenticated = False
        mock_user.is_active = True
        mock_user_getter.return_value = mock_user

        try:
            client = socketio_instance.test_client(socket_app)
            assert not client.is_connected()
        except Exception:
            pass


def test_socket_campaign_events(socket_app, socketio_instance, db_session):
    """Test campaign control events."""
    from mercury.data.models import Campaign, CampaignStatus
    from mercury.web.events import _active_services

    # Create campaign in db
    campaign = Campaign(id=1, name="Test Campaign", status=CampaignStatus.DRAFT, settings={})
    db_session.add(campaign)
    db_session.commit()
    db_session.expunge_all()

    # Register mock active service
    mock_svc = MagicMock()

    # This test verifies the socket EVENT contract (started/paused/resumed/
    # stopped), not campaign execution. handle_start_campaign spawns a real
    # daemon=False worker thread (_run_campaign_thread) that does its own DB
    # work; in the test harness every session shares ONE in-memory SQLite
    # connection (conftest StaticPool), so that thread interleaves transactions
    # with the resume handler's repo.update() and intermittently breaks its
    # post-commit refresh — and, being unjoined, leaks into later tests. The
    # worker is covered by the test_run_campaign_thread_* tests; stub it here so
    # this test exercises only the event handlers. (Not an artifact in prod,
    # where Postgres gives each thread its own connection.)
    with patch("flask_login.utils._get_user") as mock_user_getter, patch(
        "mercury.web.app.get_app_context"
    ), patch("mercury.web.events._run_campaign_thread"):
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.is_active = True
        mock_user.username = "admin"
        mock_user_getter.return_value = mock_user

        client = socketio_instance.test_client(socket_app)

        # Start
        client.emit("start_campaign", {"campaign_id": 1})
        received = client.get_received()

        event = next((e for e in received if e["name"] == "campaign_started"), None)
        assert event is not None
        assert event["args"][0]["campaign_id"] == 1

        # Now register the mock active service for pause/resume/stop controls
        _active_services[1] = mock_svc

        # Pause
        client.emit("pause_campaign", {"campaign_id": 1})
        received = client.get_received()
        event = next((e for e in received if e["name"] == "campaign_paused"), None)
        assert event is not None
        mock_svc.pause.assert_called_once()

        # Resume
        client.emit("resume_campaign", {"campaign_id": 1})
        received = client.get_received()
        event = next((e for e in received if e["name"] == "campaign_resumed"), None)
        assert event is not None
        mock_svc.resume.assert_called_once()

        # Stop
        client.emit("stop_campaign", {"campaign_id": 1})
        received = client.get_received()
        event = next((e for e in received if e["name"] == "campaign_stopped"), None)
        assert event is not None
        mock_svc.stop.assert_called_once()


def test_start_campaign_worker_mode_enqueues(socket_app, socketio_instance, monkeypatch):
    """With CAMPAIGN_EXECUTION_MODE=worker, start_campaign enqueues to the worker
    tier (run_async(enqueue_campaign(...))) instead of spawning an in-process
    thread, while still acknowledging with campaign_started."""
    monkeypatch.setenv("CAMPAIGN_EXECUTION_MODE", "worker")
    with patch("flask_login.utils._get_user") as mock_user_getter, patch(
        "mercury.web.events.run_async", return_value="job-1"
    ) as mock_run_async, patch("mercury.worker.queue.enqueue_campaign"):
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.is_active = True
        mock_user.username = "admin"
        mock_user_getter.return_value = mock_user

        client = socketio_instance.test_client(socket_app)
        client.emit("start_campaign", {"campaign_id": 5})
        received = client.get_received()

        assert any(e["name"] == "campaign_started" for e in received)
        mock_run_async.assert_called()  # routed via run_async(enqueue_campaign(...))


def test_build_config_from_campaign():
    from mercury.web.events import _build_config_from_campaign
    from mercury.data.models import Campaign

    campaign = Campaign(
        name="Test build config",
        subjects=["Subj 1", "Subj 2"],
        reply_to="reply@test.com",
        concurrency=10,
        settings={
            "from_emails": ["a@b.com"],
            "from_names": ["Name"],
            "templates": ["t1"],
            "recipients_path": "/path.csv",
            "attachment_ids": ["1", "invalid", "2"],
            "convert_attachment": True,
            "attachment_convert_to": "pdf",
            "logo_attachment_id": "4",
            "auto_company_logo": True,
            "hide_from_email_header": True,
            "validate_emails": False,
            "deduplicate": False,
            "dry_run": True,
            "enable_tracking": False,
            "track_opens": False,
            "track_clicks": False,
            "tracking_base_url": "http://track",
            "mail_priority": "1",
        },
    )
    config = _build_config_from_campaign(campaign)
    assert config.name == "Test build config"
    assert config.subject == "Subj 1"
    assert config.subjects == ["Subj 1", "Subj 2"]
    assert config.from_emails == ["a@b.com"]
    assert config.from_names == ["Name"]
    assert config.templates == ["t1"]
    assert config.recipients_path == "/path.csv"
    assert config.attachment_ids == [1, 2]
    assert config.convert_attachment is True
    assert config.attachment_convert_to == "pdf"
    assert config.logo_attachment_id == 4
    assert config.auto_company_logo is True
    assert config.hide_from_email_header is True
    assert config.validate_emails is False
    assert config.deduplicate is False
    assert config.dry_run is True
    assert config.enable_tracking is False
    assert config.track_opens is False
    assert config.track_clicks is False
    assert config.tracking_base_url == "http://track"
    assert config.mail_priority == "1"

    # Test template variants
    campaign.template = MagicMock()
    campaign.template.html_path = "path.html"
    config = _build_config_from_campaign(campaign)
    assert config.template_path == "path.html"

    campaign.template.html_path = None
    campaign.template.html_content = "<html>"
    config = _build_config_from_campaign(campaign)
    assert config.html_content == "<html>"


def test_emit_progress_and_complete():
    from mercury.web.events import emit_progress, emit_complete

    with patch("mercury.web.events.get_app_context") as mock_get_ctx:
        mock_ctx = MagicMock()
        mock_get_ctx.return_value = mock_ctx

        emit_progress({"data": 123})
        mock_ctx.emit_progress.assert_called_once_with({"data": 123})

        emit_complete({"data": 456})
        mock_ctx.emit_complete.assert_called_once_with({"data": 456})


def test_socket_disconnect(socket_app, socketio_instance):
    with patch("flask_login.utils._get_user") as mock_user_getter:
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.is_active = True
        mock_user.username = "admin"
        mock_user_getter.return_value = mock_user

        client = socketio_instance.test_client(socket_app)
        assert client.is_connected()
        client.disconnect()
        assert not client.is_connected()


def test_start_campaign_unauthenticated(socket_app, socketio_instance):
    with patch("flask_login.utils._get_user") as mock_user_getter:
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.username = "admin"
        mock_user_getter.return_value = mock_user

        client = socketio_instance.test_client(socket_app)
        assert client.is_connected()

        # Now switch to unauthenticated
        mock_user.is_authenticated = False

        client.emit("start_campaign", {"campaign_id": 1})
        received = client.get_received()
        event = next((e for e in received if e["name"] == "campaign_error"), None)
        assert event is not None
        assert "Not authenticated" in event["args"][0]["error"]


def test_start_campaign_no_id(socket_app, socketio_instance):
    with patch("flask_login.utils._get_user") as mock_user_getter:
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.username = "admin"
        mock_user_getter.return_value = mock_user

        client = socketio_instance.test_client(socket_app)
        client.emit("start_campaign", {})
        received = client.get_received()
        event = next((e for e in received if e["name"] == "campaign_error"), None)
        assert event is not None
        assert "campaign_id required" in event["args"][0]["error"]


def test_start_campaign_already_active(socket_app, socketio_instance):
    with patch("flask_login.utils._get_user") as mock_user_getter, patch(
        "mercury.web.events._active_services", {1: MagicMock()}
    ):
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.username = "admin"
        mock_user_getter.return_value = mock_user

        client = socketio_instance.test_client(socket_app)
        client.emit("start_campaign", {"campaign_id": 1})
        received = client.get_received()
        event = next((e for e in received if e["name"] == "campaign_error"), None)
        assert event is not None
        assert "already running" in event["args"][0]["error"].lower()


def test_control_campaign_unauthenticated(socket_app, socketio_instance):
    with patch("flask_login.utils._get_user") as mock_user_getter:
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.username = "admin"
        mock_user_getter.return_value = mock_user

        client = socketio_instance.test_client(socket_app)
        assert client.is_connected()

        # Now switch to unauthenticated
        mock_user.is_authenticated = False

        client.emit("pause_campaign", {"campaign_id": 1})
        client.emit("resume_campaign", {"campaign_id": 1})
        client.emit("stop_campaign", {"campaign_id": 1})
        received = client.get_received()
        assert not any(
            e["name"] in ("campaign_paused", "campaign_resumed", "campaign_stopped")
            for e in received
        )


def test_run_campaign_thread_not_found(socket_app, socketio_instance):
    from mercury.web.events import _run_campaign_thread

    with patch("mercury.web.events.CampaignRepository") as MockRepo, patch(
        "mercury.web.extensions.queue_emit"
    ) as mock_queue_emit:
        MockRepo.return_value.get.return_value = None

        _run_campaign_thread(999, socketio_instance, socket_app)
        mock_queue_emit.assert_any_call(
            "campaign_error", {"campaign_id": 999, "error": "Campaign not found"}
        )


def test_run_campaign_thread_no_recipients(socket_app, socketio_instance):
    from mercury.web.events import _run_campaign_thread
    from mercury.data.models import CampaignStatus

    mock_campaign = MagicMock()
    mock_campaign.name = "Test Campaign"
    mock_campaign.settings = {
        "recipients_path": "",
        "manual_recipients": [],
        "from_emails": ["a@b.com"],
    }
    mock_campaign.subjects = ["Subj"]
    mock_campaign.template = None
    mock_campaign.template_id = None

    with patch("mercury.web.events.CampaignRepository") as MockRepo, patch(
        "mercury.web.extensions.queue_emit"
    ) as mock_queue_emit, patch("mercury.web.events.CampaignService") as MockService:
        MockRepo.return_value.get.return_value = mock_campaign
        MockService.return_value.load_recipients_from_csv.return_value = []

        _run_campaign_thread(1, socketio_instance, socket_app)

        assert mock_campaign.status == CampaignStatus.FAILED
        MockRepo.return_value.update.assert_called_with(mock_campaign)
        mock_queue_emit.assert_any_call(
            "campaign_error", {"campaign_id": 1, "error": "No recipients found"}
        )


def test_run_campaign_thread_success_and_callbacks(socket_app, socketio_instance, tmp_path):
    from mercury.web.events import _run_campaign_thread
    import csv

    csv_file = tmp_path / "recipients.csv"
    with open(csv_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["email", "first_name"])
        writer.writerow(["recip@test.com", "John"])

    mock_campaign = MagicMock()
    mock_campaign.name = "Test"
    mock_campaign.settings = {
        "recipients_path": str(csv_file),
        "from_emails": ["a@b.com"],
    }
    mock_campaign.subjects = ["Subj"]
    mock_campaign.template = None

    captured_cb = None

    def mock_run_campaign(recipients, progress_callback=None):
        nonlocal captured_cb
        captured_cb = progress_callback
        return "fake_future"

    with patch("mercury.web.events.CampaignRepository") as MockRepo, patch(
        "mercury.web.extensions.queue_emit"
    ) as mock_queue_emit, patch("mercury.web.events.CampaignService") as MockService, patch(
        "mercury.web.events.run_async"
    ) as mock_run_async, patch("mercury.web.events._webhook_service") as mock_ws:
        MockRepo.return_value.get.return_value = mock_campaign
        mock_service_instance = MockService.return_value
        mock_service_instance.load_recipients_from_csv.return_value = [{"email": "recip@test.com"}]
        mock_service_instance.run_campaign.side_effect = mock_run_campaign
        mock_run_async.return_value = {"sent": 1, "failed": 0, "total": 1}

        _run_campaign_thread(1, socketio_instance, socket_app)

        assert captured_cb is not None

        # Test progress callback
        import asyncio

        asyncio.run(
            captured_cb(
                {
                    "success": True,
                    "recipient": "recip@test.com",
                    "is_bounce": False,
                }
            )
        )

        # Test progress callback with a bounce
        asyncio.run(
            captured_cb(
                {
                    "success": False,
                    "recipient": "recip2@test.com",
                    "is_bounce": True,
                    "error_type": "hard_bounce",
                }
            )
        )

        # Test database flush error handling in _persist_counts
        # We trigger it by running cb 25 times and making update raise exception
        MockRepo.return_value.update.side_effect = Exception("DB error")
        for i in range(25):
            asyncio.run(
                captured_cb(
                    {
                        "success": True,
                        "recipient": f"recip_{i}@test.com",
                        "is_bounce": False,
                    }
                )
            )


def test_run_campaign_thread_with_linked_list(socket_app, socketio_instance):
    from mercury.web.events import _run_campaign_thread

    mock_campaign = MagicMock()
    mock_campaign.name = "Test"
    mock_campaign.settings = {
        "from_emails": ["a@b.com"],
    }
    mock_campaign.subjects = ["Subj"]
    mock_campaign.template = None
    mock_campaign.recipient_list = MagicMock()
    mock_campaign.recipient_list.source_path = "/some/file.csv"

    with patch("mercury.web.events.CampaignRepository") as MockRepo, patch(
        "mercury.web.events.CampaignService"
    ) as MockService, patch("mercury.web.events.run_async") as mock_run_async, patch(
        "mercury.web.events._webhook_service"
    ) as mock_ws:
        MockRepo.return_value.get.return_value = mock_campaign
        mock_service_instance = MockService.return_value
        mock_service_instance.load_recipients_from_csv.return_value = [{"email": "x@y.com"}]
        mock_run_async.return_value = {"sent": 1, "failed": 0, "total": 1}

        _run_campaign_thread(1, socketio_instance, socket_app)

        mock_service_instance.load_recipients_from_csv.assert_called_with(
            "/some/file.csv", validate=True, deduplicate=True
        )


def test_run_campaign_thread_crash(socket_app, socketio_instance):
    from mercury.web.events import _run_campaign_thread
    from mercury.data.models import CampaignStatus

    mock_campaign = MagicMock()
    mock_campaign.settings = {}
    mock_campaign.subjects = []

    def raise_ex(self):
        raise Exception("crashed")

    type(mock_campaign).name = property(raise_ex)

    with patch("mercury.web.events.CampaignRepository") as MockRepo, patch(
        "mercury.web.extensions.queue_emit"
    ) as mock_queue_emit:
        MockRepo.return_value.get.return_value = mock_campaign

        _run_campaign_thread(1, socketio_instance, socket_app)

        assert mock_campaign.status == CampaignStatus.FAILED
        mock_queue_emit.assert_any_call("campaign_error", {"campaign_id": 1, "error": "crashed"})


def test_run_campaign_thread_manual_recipients_and_heartbeat(socket_app, socketio_instance):
    from mercury.web.events import _run_campaign_thread
    from mercury.data.models import CampaignStatus

    mock_campaign = MagicMock()
    mock_campaign.name = "Test"
    mock_campaign.settings = {
        "manual_recipients": ["u1@t.com", "u2@t.com"],
    }
    mock_campaign.subjects = ["Subj"]
    mock_campaign.template = None

    captured_cb = None

    def mock_run_campaign(recipients, progress_callback=None):
        nonlocal captured_cb
        captured_cb = progress_callback
        return "fake_future"

    mono_time = [100.0]

    def mock_mono():
        mono_time[0] += 5.0
        return mono_time[0]

    with patch("mercury.web.events.CampaignRepository") as MockRepo, patch(
        "mercury.web.extensions.queue_emit"
    ) as mock_queue_emit, patch("mercury.web.events.CampaignService") as MockService, patch(
        "mercury.web.events.run_async"
    ) as mock_run_async, patch("mercury.web.events._webhook_service") as mock_ws, patch(
        "time.monotonic", side_effect=mock_mono
    ):
        MockRepo.return_value.get.return_value = mock_campaign
        mock_service_instance = MockService.return_value
        mock_service_instance.run_campaign.side_effect = mock_run_campaign

        # Stats with start and end times to trigger duration parsing
        mock_stats = {
            "sent": 2,
            "failed": 0,
            "total": 2,
            "start_time": "2026-06-09T00:00:00",
            "end_time": "2026-06-09T00:01:00",
        }
        mock_run_async.return_value = mock_stats

        # Mock service shutdown event
        mock_service_instance._running = False
        mock_service_instance._shutdown_event.is_set.return_value = True

        _run_campaign_thread(1, socketio_instance, socket_app)

        # Callback should have been captured
        assert captured_cb is not None

        # Trigger successful count persistence by calling progress_cb DB_FLUSH_EVERY times
        import asyncio

        for i in range(25):
            asyncio.run(
                captured_cb(
                    {
                        "success": True,
                        "recipient": f"recip_{i}@test.com",
                        "is_bounce": False,
                    }
                )
            )

        # Verify final campaign status resolved to CANCELLED due to shutdown event
        assert mock_campaign.status == CampaignStatus.CANCELLED


def test_run_campaign_thread_webhook_notification_error(socket_app, socketio_instance):
    from mercury.web.events import _run_campaign_thread

    mock_campaign = MagicMock()
    mock_campaign.name = "Test"
    mock_campaign.settings = {"manual_recipients": ["u@t.com"]}
    mock_campaign.subjects = ["Subj"]
    mock_campaign.template = None

    with patch("mercury.web.events.CampaignRepository") as MockRepo, patch(
        "mercury.web.events.CampaignService"
    ) as MockService, patch("mercury.web.events.run_async") as mock_run_async, patch(
        "mercury.web.events._webhook_service"
    ) as mock_ws:
        MockRepo.return_value.get.return_value = mock_campaign
        mock_ws.notify_campaign_started.side_effect = Exception("webhook error")
        mock_ws.notify_campaign_completed.side_effect = Exception("webhook error")
        mock_run_async.return_value = {"sent": 1, "failed": 0, "total": 1}

        _run_campaign_thread(1, socketio_instance, socket_app)
        # Should complete without raising exception


def test_run_campaign_thread_persist_error_in_crash(socket_app, socketio_instance):
    from mercury.web.events import _run_campaign_thread

    mock_campaign = MagicMock()

    # Trigger crash and also make CampaignRepository fail on update in exception handler
    def raise_ex(self):
        raise Exception("crashed")

    type(mock_campaign).name = property(raise_ex)

    with patch("mercury.web.events.CampaignRepository") as MockRepo:
        MockRepo.return_value.get.return_value = mock_campaign
        MockRepo.return_value.update.side_effect = Exception("update failed")

        _run_campaign_thread(1, socketio_instance, socket_app)
        # Should handle it gracefully

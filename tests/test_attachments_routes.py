"""Tests for attachments management routes."""

import os
import io
import pytest
from unittest.mock import patch, MagicMock
from flask import json
from sqlalchemy.orm import sessionmaker
from mercury.data.models import Attachment


@pytest.fixture
def app_no_login(db_engine):
    """App fixture with LOGIN_DISABLED=True."""
    from mercury.web.app import create_app
    from mercury.app_context import AppContext

    mock_context = MagicMock(spec=AppContext)
    mock_context.limiter = MagicMock()
    mock_context.limiter.limit = lambda x: lambda f: f
    mock_context.socketio = MagicMock()
    mock_context.is_initialized = False

    TestSession = sessionmaker(bind=db_engine)

    with patch("mercury.web.app.init_db"), patch(
        "mercury.security.auth.UserRepository"
    ) as MockRepo, patch("mercury.web.app.get_app_context", return_value=mock_context), patch(
        "mercury.data.database.get_session_direct", side_effect=TestSession
    ), patch("mercury.services.smtp_service.get_session_direct", side_effect=TestSession), patch(
        "mercury.services.campaign_service.get_session_direct", side_effect=TestSession
    ), patch("mercury.web.routes.api.get_session_direct", side_effect=TestSession), patch(
        "mercury.services.identity_service.get_session_direct", side_effect=TestSession
    ), patch(
        "mercury.services.settings_service.get_session_direct", side_effect=TestSession
    ), patch.dict(os.environ, {"API_KEYS": "test_api_key"}):
        MockRepo.return_value.get_admins.return_value = [MagicMock()]
        app = create_app(
            config={
                "TESTING": True,
                "WTF_CSRF_ENABLED": False,
                "LOGIN_DISABLED": True,
            }
        )
        yield app


@pytest.fixture
def client_no_login(app_no_login):
    return app_no_login.test_client()


@pytest.fixture
def temp_attachments_dir(tmp_path):
    """Override get_data_dir to return tmp_path/data so we clean up uploads."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    
    with patch("mercury.web.routes.attachments.get_data_dir", return_value=data_dir):
        yield data_dir


def test_attachments_index(client_no_login, db_session, temp_attachments_dir):
    # Seed db with an active attachment
    a = Attachment(
        filename="test.txt",
        stored_name="test_stored.txt",
        size_bytes=10,
        content_type="text/plain",
        is_active=True
    )
    db_session.add(a)
    db_session.commit()
    
    # Create the file on disk
    (temp_attachments_dir / "attachments").mkdir(parents=True, exist_ok=True)
    (temp_attachments_dir / "attachments" / "test_stored.txt").write_text("hello world")

    response = client_no_login.get("/attachments/")
    assert response.status_code == 200
    assert b"test.txt" in response.data


def test_attachments_list_json(client_no_login, db_session, temp_attachments_dir):
    a = Attachment(
        filename="test.txt",
        stored_name="test_stored.txt",
        size_bytes=10,
        content_type="text/plain",
        is_active=True
    )
    db_session.add(a)
    db_session.commit()

    response = client_no_login.get("/attachments/list.json")
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["count"] == 1
    assert data["attachments"][0]["filename"] == "test.txt"


def test_attachments_upload_missing_file(client_no_login):
    response = client_no_login.post("/attachments/", data={})
    assert response.status_code == 400
    assert b"No file provided" in response.data


def test_attachments_upload_blocked_extension(client_no_login):
    data = {
        "file": (io.BytesIO(b"malicious content"), "hack.exe")
    }
    response = client_no_login.post("/attachments/", data=data, content_type="multipart/form-data")
    assert response.status_code == 400
    assert b"not allowed" in response.data


def test_attachments_upload_empty_file(client_no_login):
    data = {
        "file": (io.BytesIO(b""), "empty.txt")
    }
    response = client_no_login.post("/attachments/", data=data, content_type="multipart/form-data")
    assert response.status_code == 400
    assert b"empty" in response.data


def test_attachments_upload_exceeds_limit(client_no_login):
    large_data = b"x" * (25 * 1024 * 1024 + 10)
    data = {
        "file": (io.BytesIO(large_data), "too_large.txt")
    }
    response = client_no_login.post("/attachments/", data=data, content_type="multipart/form-data")
    assert response.status_code == 413
    assert b"limit" in response.data


def test_attachments_upload_success(client_no_login, temp_attachments_dir):
    data = {
        "file": (io.BytesIO(b"hello world"), "hello_{{name}}.txt"),
        "description": "My test attachment"
    }
    response = client_no_login.post("/attachments/", data=data, content_type="multipart/form-data")
    assert response.status_code == 201
    resp_data = json.loads(response.data)
    assert resp_data["attachment"]["filename"] == "hello_{{name}}.txt"
    assert resp_data["attachment"]["description"] == "My test attachment"
    
    # Check that file exists on disk
    stored_name = resp_data["attachment"]["stored_name"]
    disk_path = temp_attachments_dir / "attachments" / stored_name
    assert disk_path.is_file()
    assert disk_path.read_text() == "hello world"


def test_attachments_upload_db_fail_unlinks(client_no_login, temp_attachments_dir):
    data = {
        "file": (io.BytesIO(b"hello world"), "db_fail.txt")
    }
    with patch("mercury.web.routes.attachments.AttachmentRepository.create", side_effect=Exception("DB fail")):
        with pytest.raises(Exception, match="DB fail"):
            client_no_login.post("/attachments/", data=data, content_type="multipart/form-data")
            
    # Check that disk path was cleaned up (no orphan files)
    attachments_dir = temp_attachments_dir / "attachments"
    files = list(attachments_dir.glob("*"))
    assert len(files) == 0


def test_attachments_download_success(client_no_login, db_session, temp_attachments_dir):
    a = Attachment(
        filename="download.txt",
        stored_name="dl.txt",
        size_bytes=10,
        content_type="text/plain",
        is_active=True
    )
    db_session.add(a)
    db_session.commit()
    
    # Create local file
    (temp_attachments_dir / "attachments").mkdir(parents=True, exist_ok=True)
    (temp_attachments_dir / "attachments" / "dl.txt").write_text("dl content")
    
    response = client_no_login.get(f"/attachments/{a.id}/download")
    assert response.status_code == 200
    assert response.data == b"dl content"


def test_attachments_download_not_found(client_no_login):
    response = client_no_login.get("/attachments/999/download")
    assert response.status_code == 404


def test_attachments_download_file_missing_on_disk(client_no_login, db_session):
    a = Attachment(
        filename="download.txt",
        stored_name="missing.txt",
        size_bytes=10,
        content_type="text/plain",
        is_active=True
    )
    db_session.add(a)
    db_session.commit()
    
    response = client_no_login.get(f"/attachments/{a.id}/download")
    assert response.status_code == 404


def test_attachments_delete_success(client_no_login, db_session, temp_attachments_dir):
    a = Attachment(
        filename="del.txt",
        stored_name="todelete.txt",
        size_bytes=10,
        content_type="text/plain",
        is_active=True
    )
    db_session.add(a)
    db_session.commit()
    
    (temp_attachments_dir / "attachments").mkdir(parents=True, exist_ok=True)
    disk_path = temp_attachments_dir / "attachments" / "todelete.txt"
    disk_path.write_text("content")
    assert disk_path.is_file()
    
    response = client_no_login.delete(f"/attachments/{a.id}")
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["deleted"] is True
    
    # Verify file deleted from disk
    assert not disk_path.is_file()


def test_attachments_delete_not_found(client_no_login):
    response = client_no_login.delete("/attachments/999")
    assert response.status_code == 404

"""Tests for recipients API."""

import io
import os
import json
from unittest.mock import patch

from mercury.web.routes.api.recipients import _recipients_dir


def test_recipients_dir_creation():
    with patch("mercury.utils.app_dirs.get_data_dir", return_value="/tmp/test_mercury_data"):
        with patch("os.makedirs") as mock_makedirs:
            path = _recipients_dir()
            assert path == "/tmp/test_mercury_data/recipients"
            mock_makedirs.assert_called_once_with("/tmp/test_mercury_data/recipients", exist_ok=True)


def test_upload_recipients_plaintext_fallback(client, auth_headers):
    import tempfile
    data = {"file": (io.BytesIO(b"user1@test.com\nnot_an_email\nuser2@test.com"), "plain.txt")}
    
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("mercury.web.routes.api.recipients._recipients_dir", return_value=tmpdir):
            response = client.post(
                "/api/recipients/upload",
                data=data,
                headers=auth_headers,
                content_type="multipart/form-data"
            )
            assert response.status_code == 200
            resp_data = json.loads(response.data)
            assert resp_data["total_raw"] == 2


def test_upload_recipients_validation_removed(client, auth_headers):
    import tempfile
    csv_content = b"email,name\nuser1@test.com,User 1\ninvalid_email,User 2"
    data = {"file": (io.BytesIO(csv_content), "mixed.csv"), "validate": "true"}
    
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("mercury.web.routes.api.recipients._recipients_dir", return_value=tmpdir):
            response = client.post(
                "/api/recipients/upload",
                data=data,
                headers=auth_headers,
                content_type="multipart/form-data"
            )
            assert response.status_code == 200
            resp_data = json.loads(response.data)
            assert resp_data["invalid_removed"] == 1
            assert resp_data["saved"] == 1


def test_upload_recipients_deduplicate_removed(client, auth_headers):
    import tempfile
    csv_content = b"email,name\nuser1@test.com,User 1\nuser1@test.com,User 2"
    data = {"file": (io.BytesIO(csv_content), "dup.csv"), "deduplicate": "true"}
    
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("mercury.web.routes.api.recipients._recipients_dir", return_value=tmpdir):
            response = client.post(
                "/api/recipients/upload",
                data=data,
                headers=auth_headers,
                content_type="multipart/form-data"
            )
            assert response.status_code == 200
            resp_data = json.loads(response.data)
            assert resp_data["duplicates_removed"] == 1
            assert resp_data["saved"] == 1


def test_preview_recipients_limit_break(client, auth_headers):
    import tempfile
    csv_content = b"email\n" + b"\n".join(f"user{i}@test.com".encode() for i in range(25))
    
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("mercury.web.routes.api.recipients._safe_filename", return_value="test.csv"):
            with patch("mercury.web.routes.api.recipients._recipients_dir", return_value=tmpdir):
                fpath = os.path.join(tmpdir, "test.csv")
                with open(fpath, "wb") as f:
                    f.write(csv_content)
                
                response = client.get("/api/recipients/test.csv/preview?limit=10", headers=auth_headers)
                assert response.status_code == 200
                resp_data = json.loads(response.data)
                assert resp_data["count"] == 10


def test_delete_recipient_file_exception(client, auth_headers):
    with patch("mercury.web.routes.api.recipients._safe_filename", return_value="test.csv"):
        with patch("mercury.web.routes.api.recipients._recipients_dir", return_value="/tmp"):
            with patch("os.path.isfile", return_value=True):
                with patch("os.remove", side_effect=Exception("Permission denied")):
                    response = client.delete("/api/recipients/test.csv", headers=auth_headers)
                    assert response.status_code == 500
                    resp_data = json.loads(response.data)
                    assert "Permission denied" in resp_data["error"]

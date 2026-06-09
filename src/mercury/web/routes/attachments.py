"""Attachments management routes.

UI + JSON-ish endpoints for the reusable attachment library. Files live
on disk under ``<data_dir>/attachments/<stored_name>``; the DB row is
the manifest. The disk path is *never* constructed from user input —
``stored_name`` is a fresh UUID4 generated at upload time.
"""
from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

from flask import (
    Blueprint,
    abort,
    jsonify,
    render_template,
    request,
    send_file,
)
from flask_login import login_required

from ...data.database import session_scope
from ...data.models import Attachment
from ...data.repositories import AttachmentRepository
from ...utils.app_dirs import get_data_dir

attachments_bp = Blueprint("attachments", __name__, url_prefix="/attachments")

# 25 MB — typical SMTP/Gmail/Outlook attachment ceiling. Refusing here is
# friendlier than failing per-recipient at send time.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

# Block obvious-trouble extensions to keep operators from accidentally
# emailing themselves into a spam-filter incident. Not a security
# boundary — content-type is not authenticated either way; this is UX.
_BLOCKED_EXTENSIONS = {
    "exe",
    "bat",
    "cmd",
    "com",
    "msi",
    "scr",
    "cpl",
    "vbs",
    "vbe",
    "js",
    "jse",
    "wsf",
    "wsh",
    "ps1",
    "sh",
}


def _attachments_dir() -> Path:
    path = get_data_dir() / "attachments"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _split_ext(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower().lstrip(".")
    return ext if ext.isalnum() and len(ext) <= 16 else ""


@attachments_bp.route("", methods=["GET"])
@attachments_bp.route("/", methods=["GET"])
@login_required
def index():
    """Attachments library page."""
    with session_scope() as session:
        rows = AttachmentRepository(session).list_active()
        attachments = [a.to_dict() for a in rows]
    return render_template("attachments.html", attachments=attachments)


@attachments_bp.route("/list.json", methods=["GET"])
@login_required
def list_json():
    """Compact JSON list for picker UIs (e.g. campaign form).

    Kept under the same blueprint so the auth contract stays uniform —
    same session check, same CSRF exemption surface (none — GETs only).
    """
    with session_scope() as session:
        rows = AttachmentRepository(session).list_active()
        items = [
            {
                "id": a.id,
                "filename": a.filename,
                "size_bytes": a.size_bytes,
                "content_type": a.content_type,
                "description": a.description or "",
            }
            for a in rows
        ]
    return jsonify({"attachments": items, "count": len(items)})


@attachments_bp.route("", methods=["POST"])
@attachments_bp.route("/", methods=["POST"])
@login_required
def upload():
    """Accept a multipart file upload and persist it."""
    file = request.files.get("file")
    if file is None or file.filename == "":
        return jsonify({"error": "No file provided"}), 400

    # secure_filename strips curly braces, but operators want placeholders in filenames.
    # The display_name is only used for MIME generation, not file storage paths.
    raw_name = os.path.basename(file.filename.replace('\\', '/')).strip()
    display_name = re.sub(r'[\x00-\x1f\x7f]+', '', raw_name) or "upload.bin"
    ext = _split_ext(display_name)
    if ext in _BLOCKED_EXTENSIONS:
        return jsonify({"error": f"Files of type .{ext} are not allowed"}), 400

    # Read once to enforce size cap before writing to disk. For 25 MB this
    # is fine in memory; if the cap ever grows, switch to streaming with
    # a running counter and unlink-on-overflow.
    data = file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        return jsonify({"error": f"File exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit"}), 413
    if not data:
        return jsonify({"error": "File is empty"}), 400

    stored_name = f"{uuid.uuid4().hex}{('.' + ext) if ext else ''}"
    disk_path = _attachments_dir() / stored_name
    disk_path.write_bytes(data)

    description = (request.form.get("description") or "").strip() or None

    try:
        with session_scope() as session:
            repo = AttachmentRepository(session)
            row = Attachment(
                filename=display_name,
                stored_name=stored_name,
                size_bytes=len(data),
                content_type=file.mimetype or None,
                description=description,
                tags=[],
                is_active=True,
            )
            repo.create(row)
            payload = row.to_dict()
    except Exception:
        # If DB insert fails after we wrote the file, don't leave an
        # orphan on disk.
        try:
            disk_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise

    return jsonify({"attachment": payload}), 201


@attachments_bp.route("/<int:attachment_id>/download", methods=["GET"])
@login_required
def download(attachment_id: int):
    """Stream the underlying file back to the browser."""
    with session_scope() as session:
        row = AttachmentRepository(session).get(attachment_id)
        if row is None or not row.is_active:
            abort(404)
        stored_name = row.stored_name
        display = row.filename
        mimetype = row.content_type or "application/octet-stream"

    disk_path = _attachments_dir() / stored_name
    if not disk_path.is_file():
        abort(404)

    return send_file(
        disk_path,
        mimetype=mimetype,
        as_attachment=True,
        download_name=display,
    )


@attachments_bp.route("/<int:attachment_id>", methods=["DELETE"])
@login_required
def delete(attachment_id: int):
    """Remove the attachment row and its on-disk file."""
    with session_scope() as session:
        repo = AttachmentRepository(session)
        row = repo.get(attachment_id)
        if row is None:
            return jsonify({"error": "Not found"}), 404
        stored_name = row.stored_name
        repo.delete(row)

    disk_path = _attachments_dir() / stored_name
    try:
        disk_path.unlink(missing_ok=True)
    except OSError:
        # The DB row is gone; the orphan file is recoverable manually.
        # Don't block the request on filesystem cleanup.
        pass

    return jsonify({"deleted": True})

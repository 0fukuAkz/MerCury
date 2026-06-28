"""Recipient-list file management API routes.

Handles CSV/TXT recipient file uploads, listing, preview and deletion under
``data/recipients/``. All filenames are sanitized at the boundary to prevent
path traversal.
"""

import csv
import io
import logging
import os
import re
from datetime import datetime, UTC

from flask import jsonify, request

from . import (
    api_bp,
    api_key_or_login_required,
    limiter,
)

logger = logging.getLogger(__name__)


def _recipients_dir() -> str:
    """Return the absolute path to the data/recipients directory, creating it if needed."""
    from ....utils.app_dirs import get_data_dir

    base = os.path.join(get_data_dir(), "recipients")
    os.makedirs(base, exist_ok=True)
    return base


def _safe_filename(name: str) -> str:
    """Sanitize a filename to prevent path traversal."""
    name = os.path.basename(name)
    name = re.sub(r"[^\w\s.\-]", "_", name)
    return name or "upload.csv"


@api_bp.route("/recipients", methods=["GET"])
@api_key_or_login_required
@limiter.limit("30/minute")
def api_list_recipient_files():
    """List all recipient list files in data/recipients/."""
    base = _recipients_dir()
    files = []
    for fname in sorted(os.listdir(base)):
        fpath = os.path.join(base, fname)
        if os.path.isfile(fpath) and fname.lower().endswith((".csv", ".txt")):
            stat = os.stat(fpath)
            files.append(
                {
                    "filename": fname,
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
                }
            )
    return jsonify({"files": files, "count": len(files)})


@api_bp.route("/recipients/upload", methods=["POST"])
@api_key_or_login_required
@limiter.limit("10/minute")
def api_upload_recipients():
    """Upload a CSV/TXT recipient file with optional validation and deduplication."""
    uploaded = request.files.get("file")
    if not uploaded:
        return jsonify({"error": "No file uploaded"}), 400

    validate = request.form.get("validate", "true").lower() in ("true", "1", "yes")
    deduplicate = request.form.get("deduplicate", "true").lower() in ("true", "1", "yes")

    raw = uploaded.stream.read().decode("utf-8", errors="replace")
    filename = _safe_filename(uploaded.filename or "upload.csv")

    # Parse as CSV; fall back to plain-text (one email per line)
    email_rgx = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    rows = []
    fieldnames = []
    try:
        reader = csv.DictReader(io.StringIO(raw))
        if reader.fieldnames and any(f.lower().strip() == "email" for f in reader.fieldnames):
            fieldnames = [f.strip() for f in reader.fieldnames]
            for row in reader:
                rows.append({k.strip(): v.strip() for k, v in row.items()})
        else:
            raise ValueError("no email column")
    except Exception:
        # Plain-text fallback — one email per line
        fieldnames = ["email"]
        rows = [
            {"email": line.strip()} for line in raw.splitlines() if line.strip() and "@" in line
        ]

    total_raw = len(rows)

    # Validate email format
    invalid_count = 0
    if validate:
        valid_rows = []
        for r in rows:
            email = r.get("email", "").lower().strip()
            if email_rgx.match(email):
                r["email"] = email
                valid_rows.append(r)
            else:
                invalid_count += 1
        rows = valid_rows

    # Deduplicate
    dup_count = 0
    if deduplicate:
        seen = set()
        deduped = []
        for r in rows:
            key = r.get("email", "").lower()
            if key not in seen:
                seen.add(key)
                deduped.append(r)
            else:
                dup_count += 1
        rows = deduped

    # Write processed file
    base = _recipients_dir()
    dest = os.path.join(base, filename)
    with open(dest, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return jsonify(
        {
            "success": True,
            "filename": filename,
            "total_raw": total_raw,
            "invalid_removed": invalid_count,
            "duplicates_removed": dup_count,
            "saved": len(rows),
        }
    )


@api_bp.route("/recipients/<filename>/preview", methods=["GET"])
@api_key_or_login_required
@limiter.limit("30/minute")
def api_preview_recipients(filename: str):
    """Return the first N rows of a recipient file."""
    filename = _safe_filename(filename)
    fpath = os.path.join(_recipients_dir(), filename)
    if not os.path.isfile(fpath):
        return jsonify({"error": "File not found"}), 404

    limit = min(int(request.args.get("limit", 20)), 200)
    rows = []
    fieldnames = []
    with open(fpath, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        for i, row in enumerate(reader):
            if i >= limit:
                break
            rows.append(dict(row))

    return jsonify({"filename": filename, "columns": fieldnames, "rows": rows, "count": len(rows)})


@api_bp.route("/recipients/<filename>", methods=["DELETE"])
@api_key_or_login_required
@limiter.limit("10/minute")
def api_delete_recipient_file(filename: str):
    """Delete a recipient list file."""
    logger.info("Recipient file delete requested: %s", filename)
    filename = _safe_filename(filename)
    fpath = os.path.join(_recipients_dir(), filename)
    if not os.path.isfile(fpath):
        logger.warning("Recipient file not found for delete: %s", fpath)
        return jsonify({"error": "File not found"}), 404

    try:
        os.remove(fpath)
        logger.info("Deleted recipient file: %s", fpath)
    except Exception as e:
        logger.exception("Error deleting recipient file %s", fpath)
        return jsonify({"error": str(e)}), 500

    return jsonify({"success": True, "filename": filename})

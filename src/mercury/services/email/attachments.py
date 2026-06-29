"""Library attachment materialization.

For each ``config.attachment_ids`` row: load the file off disk, run
placeholder substitution on the filename (always) and on text/*
content (when applicable), and optionally pipe it through
AttachmentGenerator to convert HTML source → PDF/DOCX/PNG/QR before
attaching.

Returns a list of plain dicts the engine knows how to attach. Failures
log and skip rather than abort the whole send — one bad row shouldn't
take down a 10k-recipient campaign.
"""
import logging
import os
from typing import Any, Dict, List, Optional

from ...data.database import session_scope
from ...data.repositories import AttachmentRepository
from ...features.generators import AttachmentGenerator
from ...features.placeholders import PlaceholderProcessor
from ...utils.app_dirs import get_data_dir
from .context import SendContext

logger = logging.getLogger(__name__)


def materialize_library_attachments(
    ctx: SendContext,
    body_extras: Dict[str, str],
    header_extras: Dict[str, str],
    placeholder_processor: Optional[PlaceholderProcessor],
    attachment_generator: Optional[AttachmentGenerator],
) -> List[Dict[str, Any]]:
    """Load and materialize all library attachments referenced by ``ctx.config``.

    Returns ``[]`` if no ``attachment_ids`` are configured.
    """
    if not ctx.config.attachment_ids:
        return []

    lib_dir = get_data_dir() / "attachments"
    library_files: List[Dict[str, Any]] = []

    convert_on = bool(ctx.config.convert_attachment)
    convert_to = (ctx.config.attachment_convert_to or "").strip().lower() or None
    if convert_on and not convert_to:
        logger.warning(
            "[attach] convert_attachment is on but no target format set; " "skipping conversion"
        )
        convert_on = False

    with session_scope() as session:
        repo = AttachmentRepository(session)
        for att_id in ctx.config.attachment_ids:
            row = repo.get(int(att_id))
            if row is None or not row.is_active:
                logger.warning(f"[attach] id={att_id} missing/inactive in DB; skipping")
                continue
            disk_path = lib_dir / (row.stored_name or "")
            if not disk_path.is_file():
                logger.error(
                    f"[attach] id={att_id} ({row.filename}) missing on disk at {disk_path}"
                )
                continue

            blob = disk_path.read_bytes()
            src_ctype = row.content_type or "application/octet-stream"
            final_filename = row.filename or ""
            final_ctype = src_ctype
            final_data: Any = blob

            # Substitute placeholders inside the filename. A library file
            # named "Report_{{first_name}}.html" arrives as
            # "Report_Alice.html" — keeps per-recipient personalization
            # consistent across body and filename.
            if placeholder_processor and "{{" in final_filename:
                try:
                    final_filename = placeholder_processor.process(
                        final_filename, ctx.placeholders, header_extras
                    )
                except Exception as e:
                    logger.warning(
                        f"[attach] id={att_id} filename placeholder substitution failed: {e}"
                    )

            # For text/* attachments, substitute placeholders inside the
            # file content too — operators expect {{first_name}} in an
            # attached HTML file to render the same way it does in the
            # email body. Binary files (PDF, PNG, DOCX) attach as-is —
            # substitution would corrupt them.
            src_maintype = src_ctype.split("/", 1)[0].lower()
            is_text = src_maintype == "text"
            if is_text and placeholder_processor:
                try:
                    decoded = blob.decode("utf-8")
                    decoded = placeholder_processor.process(decoded, ctx.placeholders, body_extras)
                    final_data = decoded.encode("utf-8")
                    blob = final_data  # so the convert path below sees the
                # already-substituted version
                except UnicodeDecodeError:
                    logger.warning(
                        f"[attach] id={att_id} content_type={src_ctype!r} "
                        f"declared text/* but bytes are not valid UTF-8; "
                        f"attaching raw without placeholder substitution"
                    )
                except Exception as e:
                    logger.warning(
                        f"[attach] id={att_id} content placeholder substitution failed: {e}"
                    )

            if convert_on and attachment_generator:
                if not is_text:
                    logger.warning(
                        f"[attach] id={att_id} content_type={src_ctype!r} "
                        f"is not text/*; convert skipped, attaching as-is"
                    )
                else:
                    try:
                        # blob is already placeholder-substituted at this
                        # point (text branch above). Decode to str for the
                        # generator.
                        html_source = blob.decode("utf-8")
                        (
                            gen_data,
                            gen_filename,
                            gen_ctype,
                        ) = attachment_generator.generate_attachment(
                            attachment_type=convert_to or "",
                            content=html_source,
                            placeholders=ctx.placeholders,
                            template_path=None,
                            link=ctx.link,
                        )
                        final_data = gen_data
                        final_ctype = gen_ctype
                        # Preserve the original basename but swap the
                        # extension so recipients see e.g. report.pdf,
                        # not report.html.pdf.
                        base, _ = os.path.splitext(final_filename)
                        ext = gen_filename.rsplit(".", 1)[-1] if "." in gen_filename else convert_to
                        final_filename = f"{base}.{ext}"
                    except Exception as e:
                        logger.error(
                            f"[attach] id={att_id} convert to {convert_to!r} failed: {e}; "
                            f"attaching original"
                        )

            library_files.append(
                {
                    "data": final_data,
                    "filename": final_filename,
                    "content_type": final_ctype,
                }
            )

    return library_files

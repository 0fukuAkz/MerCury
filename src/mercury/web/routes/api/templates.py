"""Template-related API routes."""

from flask import jsonify, request

from . import (
    api_bp,
    api_key_or_login_required,
    limiter,
    session_scope,
    TemplateRepository,
    TemplateEngine,
)


@api_bp.route("/templates", methods=["GET"])
@api_key_or_login_required
@limiter.limit("30/minute")
def api_list_templates():
    """List email templates."""
    with session_scope() as session:
        repo = TemplateRepository(session)
        templates = repo.get_active()
        return jsonify({"templates": [t.to_dict() for t in templates]})


@api_bp.route("/templates/preview", methods=["POST"])
@api_key_or_login_required
@limiter.limit("20/minute")
def api_preview_template():
    """Preview template with sample data."""
    data = request.get_json(silent=True) or {}

    engine = TemplateEngine(html_content=data.get("html", ""))
    preview = engine.preview(
        recipient=data.get("recipient", "test@example.com"),
        extra_placeholders=data.get("placeholders", {}),
    )

    return jsonify(
        {
            "html": preview,
            "placeholders": engine.get_used_placeholders(),
        }
    )

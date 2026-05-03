"""API blueprint, split by resource.

This package replaces the former 1092-line ``api.py`` module. Each sub-module
registers its routes against the shared ``api_bp`` defined here. The blueprint
is exported at package level so existing imports continue to work:

    from mercury.web.routes.api import api_bp

The package also re-exports the dependencies used by the route handlers
(repositories, services, helpers). Submodules import from this package
rather than from absolute paths, so any test that does
``patch('mercury.web.routes.api.CampaignRepository')`` (and similar) keeps
working — the patch reaches the canonical binding the routes actually use.

Sub-modules (one per resource):
    - status         /api/status
    - campaigns      /api/campaigns/*
    - smtp           /api/smtp/*
    - templates      /api/templates*
    - logs_stats     /api/logs/* and /api/stats
    - webhooks       /api/webhooks/*
    - scheduling     /api/scheduling/jobs/*
    - bounces        /api/bounces*
    - recipients     /api/recipients/*
    - dead_letter    /api/dead-letter/*
"""

from flask import Blueprint

# ---- Re-exports used by route handlers ------------------------------------
# These are imported once here and pulled into submodules via `from . import X`.
# Patching `mercury.web.routes.api.X` therefore intercepts the route's binding.
from ...decorators import api_key_or_login_required  # noqa: F401
from ...extensions import limiter, run_async  # noqa: F401
from ....data.database import get_session_direct, session_scope  # noqa: F401
from ....data.repositories import (  # noqa: F401
    CampaignRepository,
    SMTPRepository,
    TemplateRepository,
    LogRepository,
)
from ....services.campaign_service import CampaignService, CampaignConfig  # noqa: F401
from ....services.smtp_service import SMTPService  # noqa: F401
from ....features.template_engine import TemplateEngine  # noqa: F401
from ....services.webhook_service import WebhookService, WebhookEvent  # noqa: F401
# ---------------------------------------------------------------------------

api_bp = Blueprint('api', __name__, url_prefix='/api')

# Import sub-modules at the bottom so their @api_bp.route(...) decorators run
# and register their routes on the shared blueprint.
from . import (  # noqa: E402, F401
    status,
    campaigns,
    smtp,
    templates,
    logs_stats,
    webhooks,
    scheduling,
    bounces,
    recipients,
    dead_letter,
)

__all__ = ['api_bp']

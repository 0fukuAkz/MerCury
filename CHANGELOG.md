# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> **Note on the 2.0.0 version string.** `pyproject.toml` declares
> `version = "2.0.0"` but no `1.x` git tag was ever cut. This CHANGELOG
> documents the lineage on its own terms; future releases should be tagged
> in git (`v2.0.0`, `v2.1.0`, ...) to match `pyproject.toml`.

## [Unreleased]

### Removed (BREAKING)
Backward-compatibility shims and legacy code paths were removed in a single
sweep. Migration notes per item:

- **`mercury.services.email_service` shim** — re-exported `EmailService`,
  `EmailConfig`, `SendContext`, and a handful of mock-target attributes
  (`SMTPService`, `TrackingService`, `DeadLetterService`, `AsyncEmailSender`,
  `BulkSendResult`, `EmailResult`).
  *Migration:* import from `mercury.services.email` instead. Mock patches at
  `mercury.services.email_service.SMTPService` move to
  `mercury.services.email.service.SMTPService`.
- **`mercury.data.models.template.EmailTemplate` alias** — was `Template`
  re-exported under the old name.
  *Migration:* use `Template`.
- **`SMTPServerConfig` back-compat read-through properties** (`circuit_breaker`,
  `current_minute_count`, `current_hour_count`, `total_sent`, `total_failures`,
  `consecutive_failures`).
  *Migration:* access them via `config.runtime.X`.
- **`AsyncConnectionPool.return_connection()`** — alias for
  `release_connection()`.
  *Migration:* call `release_connection()`.
- **`MERCURY_DEV` escape hatch.** No longer bypasses the SECRET_KEY or
  ADMIN_PASSWORD production hard-fails.
  *Migration:* use `FLASK_ENV=development` for local iteration; production
  must set real secrets.
- **`MERCURY_BOOT_MIGRATIONS` and `MERCURY_SKIP_BOOT_MIGRATIONS`** — env-var
  overrides for the on-boot Alembic upgrade. Behavior is now determined
  solely by `FLASK_ENV` (non-prod runs migrations, prod skips them).
  *Migration:* run `alembic upgrade head` out-of-band in production.
- **Default `admin/admin` bootstrap** — `web/app.py` no longer creates a
  default admin user when none exists. The intended secure path
  (`security.auth.init_auth`) is now wired into `create_app` and only
  creates the first admin when `ADMIN_USERNAME`, `ADMIN_PASSWORD`, and
  `ADMIN_EMAIL` are all set.
  *Migration:* set those three env vars before first boot, or create the
  admin via CLI/SQL.
- **Default `SECRET_KEY = 'dev-secret-key-change-in-prod'`** — no longer
  has a hard-coded default. Required in any non-dev environment; in dev
  it falls back to a clearly-named placeholder.
  *Migration:* set `SECRET_KEY` (e.g. `python -c 'import secrets; print(secrets.token_hex(32))'`).
- **Default `ADMIN_EMAIL = 'admin@localhost'`** — removed. `ADMIN_EMAIL` is
  now required alongside `ADMIN_USERNAME` and `ADMIN_PASSWORD`.
- **Default `TRACKING_BASE_URL = 'http://localhost:5000'`** —
  `TrackingService` raises `RuntimeError` if neither the constructor arg
  nor the env var is set. Campaigns that enable tracking without
  configuring `tracking_base_url` now silently skip tracking instead of
  pointing at localhost.
  *Migration:* set `TRACKING_BASE_URL` to your public dashboard URL.
- **`use_tls` / `use_ssl` on the SMTP API** (`POST /api/smtp`,
  `PUT /api/smtp/<name>`) — rejected with a clear error. The single
  `tls_mode` enum (`'none' | 'starttls' | 'ssl'`) is now required.
  *Migration:* clients must send `tls_mode`.
- **`use_tls` / `use_ssl` columns on the `smtpservers` table** — dropped.
  See Alembic revision `c9d4e8b1a7f2` (`20260521_0002_..._drop_legacy_use_tls_use_ssl.py`).
  Backfill is automatic: pre-existing rows had `tls_mode` kept in lockstep
  with the bools by the old setter; rows where `tls_mode` was somehow
  NULL are backfilled from the bools before the columns are removed.
  Also removed from `SMTPServer` model, `SMTPServerConfig` dataclass,
  `SMTPService.add_server(...)` kwargs, and the model's `to_dict()` /
  `get_connection_config()` output.
  *Migration:* run `alembic upgrade head` in any environment that
  predates this release. Downgrade reverses the column drop and
  re-derives the bools from `tls_mode`.
- **`SMTPServerConfig.from_dict` no longer derives `tls_mode` from
  legacy `use_tls` / `use_ssl`.** Missing `tls_mode` now defaults to
  `'starttls'`; supplying the legacy bools without `tls_mode` produces
  a `'starttls'` config (where it previously could resolve to `'ssl'`
  or `'none'` based on the bools).
  *Migration:* set `tls_mode` explicitly in any YAML config that relied
  on the bool-derivation behavior.
- **`/api/smtp/test/<int:server_id>`** — removed. Test by name only.
  *Migration:* `POST /api/smtp/test/<name>`.
- **Campaign `include_default_body` default** — was `True` (back-compat
  for clients that didn't send the field). Now defaults to `False`.
  *Migration:* clients must send the field explicitly. The web UI
  already does.
- **Removed "legacy" comments and dead `EmailTemplate` test paths** in
  `web/routes/api/campaigns_testing.py`, `web/routes/api/campaigns.py`,
  and tests.

### Security
- **Hard-fail on missing `ADMIN_PASSWORD` in production.** When `FLASK_ENV=production`
  and `ADMIN_PASSWORD` is unset, the web app raises `RuntimeError` at boot rather
  than silently creating an `admin/admin` user. (No env-var escape — see Removed.)
- **Dependency CVE refresh.** Closed 12 known vulnerabilities by pinning forward:
  `cryptography` 42.0.1 → 46.0.7 (CVE-2026-26007, PYSEC-2026-35/36),
  `flask` 3.0.0 → 3.1.3 (CVE-2026-27205),
  `gunicorn` 21.2.0 → 22.0.0 (CVE-2024-1135, CVE-2024-6827),
  `eventlet` 0.35.2 → 0.40.3 (CVE-2025-58068),
  `python-socketio` 5.11.0 → 5.14.0 (CVE-2025-61765),
  `flask-cors` 4.0.0 → 4.0.2 (PYSEC-2024-71),
  `python-dotenv` 1.0.0 → 1.2.2 (CVE-2026-28684),
  `tqdm` 4.66.1 → 4.66.3 (CVE-2024-34062).
- **MD5 usage marked `usedforsecurity=False`** in tracking link-id generation
  and placeholder seed hashing — both are non-security uses; the annotation
  documents intent and clears Bandit B324.

### Added
- `SECURITY.md` with private vulnerability reporting policy and a deployment
  hardening checklist for operators.
- `CHANGELOG.md` (this file).
- `gunicorn` and `eventlet` are now explicit runtime dependencies in
  `pyproject.toml` (they were already pinned in `requirements.txt`).
- **`Deployment.md`** — single landing-page deploy/operate doc that
  merges and refreshes the previous `INSTALL.md`, `USAGE.md`, and
  `docs/QUICKSTART.md`. The three source files were deleted. The new
  doc reflects current reality: `mercury` (not `sender`) as the CLI,
  `tls_mode` (not `use_tls`/`use_ssl`) in YAML, eventlet single-worker
  Gunicorn, the real Docker Compose layout, and the new mandatory env
  vars (`ADMIN_USERNAME`/`ADMIN_PASSWORD`/`ADMIN_EMAIL`/`TRACKING_BASE_URL`).

### Changed
- `mercury start server` now defaults to port **5000**, matching `python run.py`.
  The two runners no longer disagree on the dashboard port.
- `TrackingService` default `base_url` 8080 → 5000 (operators using non-default
  ports must set `TRACKING_BASE_URL` explicitly).

### Removed
- **`src/mercury/config.py`** — top-level YAML config helpers (`load_yaml_config`,
  `create_default_config`, `expand_env_vars`, `merge_configs`, `DEFAULT_CONFIG`).
  No production code in `src/` imported from this module; only `tests/test_config.py`
  exercised it. Tests were retired alongside the module. The live config flow
  goes through `services.campaign_service.CampaignConfig` /
  `services.email.config.EmailConfig` and is unaffected.
- **Frozen-app build pipeline**: `MerCury.spec`, `scripts/build_dmg.sh`, and
  `src/mercury/autostart.py`. The DMG build was not invoked by CI or any
  Makefile target and the last produced artifact dated to January. The
  `pywebview>=6.1` dependency was dropped from `requirements.txt` as a
  consequence.
- README and USAGE references to `mercury start server` at port 8080 were
  updated to the canonical `python run.py` on port 5000. The CLI command
  still exists (now on 5000) for local iteration.

### Fixed
- **Dead-letter "Discard All" no longer reports success while persisting nothing.**
  The bulk-update path in `DeadLetterRepository.mark_all_unresolved_as_resolved`
  now commits inside the repository call, matching the rest of `BaseRepository`.
  Previously the rows were UPDATEd but `session_scope`'s implicit close rolled the
  transaction back.
- Stale `CLAUDE.md` claim about an inline `ALTER TABLE` boot-time shim — the
  shim was already replaced with a proper Alembic-driven flow; the doc was
  updated to match reality.
- Stale documentation: removed `mercury start server` / port 8080 mismatches
  in [README.md](README.md), [USAGE.md](USAGE.md), [docs/QUICKSTART.md](docs/QUICKSTART.md),
  and [docs/API.md](docs/API.md).
- Removed unused `AttachmentGenerator` import in
  `tests/test_dynamic_content.py` (ruff F401).

### Known issues
- ~238 mypy errors remain across the source tree; CI runs mypy with
  `continue-on-error: true`. A separate pass will land before the next release.
- Bandit and pip-audit run in CI but do not gate; both use
  `continue-on-error: true` until the remaining `flask-cors` (4 → 6 major)
  and `pillow` (10 → 12 major) bumps are vetted in a dedicated dep-refresh PR.

## [2.0.0] — pre-release lineage

This range covers all work between the initial commit (2025-12-18) and the
current `main`. Commit subjects in this window are inconsistent — many are
literally `update`, `.`, or `/` — so the bullets below are sourced from the
commits whose subjects describe their content. Subsequent releases should be
tagged in git and pulled from cleaner commit messages.

### Added
- Web dashboard (`mercury.web`) with Flask + Flask-SocketIO and Gunicorn/eventlet runner (`run.py`).
- CLI front-end (`mercury` Click app) for YAML-driven campaigns.
- Async SMTP send pipeline under `mercury.engine` (connection pool, rate limiter,
  circuit breaker, retry queue, error recovery, error aggregator).
- Dead-letter queue with bulk "Discard All" action and stats endpoint.
- `mercury db migrate` / `mercury db current` CLI commands.
- Alembic migration chain (single head, `b8e4a2f1c9d6`).
- Template engine with `{{var}}` / `{{if:x}}…{{endif}}` mini-language shared by CLI and web.
- Webhook delivery service.
- SocketIO real-time campaign progress events.
- API-key authentication for `/api/*` routes via `X-API-Key` header.
- Unsubscribe-link HMAC signing.

### Changed
- Split monolithic `web/routes/api.py` (1092 LOC) into resource-scoped package.
- Extended `session_scope()` context manager to remaining web routes and tests.
- API routes adopted `session_scope()`, fixing module-caching test flakes.
- Split SMTP runtime state from configuration (Tier 2 refactor #10).
- Pinned config dataclass contracts.
- Emit `campaign_started` synchronously from the WebSocket handler.

### Removed
- Dead parallel config-dataclass hierarchy (Tier 1 refactor #2).
- `scheduled_tasks.lock` (was committed accidentally).
- `.mercury.pid` from version control.

### Fixed
- Default `SECRET_KEY` now fail-closes outside dev environments
  (`FLASK_ENV` ∉ {development, dev, test, testing, local} and `MERCURY_DEV` not set).
- Placeholder name precedence in the template engine.
- 12 latent test failures; suite reaches fully green.
- Two real bugs surfaced by CI lint cleanup pass.

### Security
- Session cookies hardened: `HttpOnly` always, `SameSite=Lax` by default,
  `Secure` in production with env override.
- CSRF protection added to form-driven routes.
- API key auth refuses to enable unless `API_KEYS` is explicitly configured
  (no fallback to an empty allowlist).

### CI
- Bumped `actions/upload-artifact` v3 → v4 (v3 is auto-rejected by GitHub).
- Added `pip install -e .` step so pytest can import `mercury` under the
  `src/` layout.

[Unreleased]: https://github.com/0fukuAkz/MerCury/compare/v2.0.0...HEAD
[2.0.0]: https://github.com/0fukuAkz/MerCury/releases/tag/v2.0.0

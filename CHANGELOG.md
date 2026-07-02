# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> **Note on the 2.0.0 version string.** `pyproject.toml` declares
> `version = "2.0.0"` but no `1.x` git tag was ever cut. This CHANGELOG
> documents the lineage on its own terms; future releases should be tagged
> in git (`v2.0.0`, `v2.1.0`, ...) to match `pyproject.toml`.

## [2.1.0] - 2026-07-01

### Added
- **Horizontal scale-out (opt-in, default-off).** The single-worker default is
  unchanged; multi-worker becomes available once shared state is externalized:
  - `SOCKETIO_MESSAGE_QUEUE=redis://...` fans live progress events out across
    web workers/replicas.
  - A campaign **worker tier** (arq): set `CAMPAIGN_EXECUTION_MODE=worker` to
    enqueue campaigns to a separate worker process instead of an in-web thread
    (`docker compose --profile worker up`). Config: `CAMPAIGN_QUEUE_REDIS`.
  - The production preflight conditionally permits `WEB_CONCURRENCY>1` when
    message-queue + redis rate-limit + worker execution are all set, and warns
    (naming what's missing) otherwise.
- **Observability.** Optional Sentry error tracking (`SENTRY_DSN`, PII-off) and
  a Prometheus `GET /metrics` endpoint — HTTP request/latency plus send-pipeline
  business metrics (`mercury_emails_sent_total`, `mercury_emails_failed_total`,
  `mercury_campaigns_active`). Optional `METRICS_TOKEN` gate.
- **Containerized deployment.** Multi-stage, non-root `Dockerfile` with a
  stdlib `HEALTHCHECK`; `docker-compose.yml` wiring Postgres + Redis + one-shot
  migrations + web, with optional `proxy` (Caddy/TLS) and `worker` profiles.
- New dependencies for the above: `redis`, `arq`, `sentry-sdk[flask]`,
  `prometheus-client` (pyproject extras: `observability`, `postgres`, `redis`,
  `worker`).
- **Packaged migrations + `mercury db` CLI.** Alembic migrations now live
  inside the package and ship in the wheel/sdist, so a `pip install
  mercury[postgres]` can create and manage its own schema — no repo checkout
  required. New commands: `mercury db migrate` / `downgrade` / `current`.
- **One-command installers.** `install.sh` (macOS/Linux) and `install.ps1`
  (Windows) create an isolated virtualenv, install MerCury, initialise the
  database, and write a login-ready `.env`. They prefer `uv` when present
  (which also sidesteps stdlib `venv` failing on uv-managed / standalone
  Pythons) and fall back to `python -m venv` + `pip`.

### Changed
- **SQLAlchemy 2.0 native typing.** All ORM models migrated from legacy
  `Column()` to `Mapped[]` / `mapped_column()`, and `Base` is now a
  `DeclarativeBase` subclass. Removed the deprecated `sqlalchemy.ext.mypy`
  plugin; `mypy src/` is plugin-free and enforced at zero errors in CI.
- Production preflight now **hard-fails** on a SQLite `DATABASE_URL` or an
  in-memory `RATE_LIMIT_STORAGE` in production (escape hatches:
  `ALLOW_SQLITE_IN_PRODUCTION`, `ALLOW_INMEMORY_RATE_LIMIT`).
- DB engine gains `pool_pre_ping` (all engines) and `pool_recycle` (networked
  engines) so a Postgres restart / idle-timeout reconnects transparently.
- CI now runs the full Alembic chain against a real Postgres service
  (`alembic upgrade head` + `alembic check`), gating migration/model drift that
  the SQLite test suite can't see.

### Fixed
- **Critical — Alembic migrations synced to the models.** A fresh Postgres
  deploy previously produced a schema the code couldn't use (missing columns
  such as `templates.subject_variants`, wrong enum types, a non-portable
  `boolean = integer` backfill). SQLite dev/tests masked this via
  `create_all`. Verified live: `alembic upgrade head` + `alembic check` clean
  on a fresh Postgres, with a campaign running end-to-end. The migration chain
  is now complete on its own — a migration adds the `users` table that only
  `create_all` had been creating — so it matches the models without relying on
  boot-time `create_all`.
- **Migrations are now SQLite-portable, not only Postgres-clean.** The
  `sync_models_with_schema` migration dropped foreign keys by their
  Postgres-generated names (`emaillogs_campaign_id_fkey`, …); SQLite doesn't
  name FK constraints, so `mercury db migrate` on a fresh SQLite DB — the
  default local/desktop path — aborted with "No such constraint" and never
  reached the `users` table. The affected batch blocks now carry an explicit FK
  naming convention and name their recreated FKs, so the full chain applies on
  SQLite *and* Postgres (verified live on both). CI now also runs the chain on
  SQLite, closing the Postgres-only gap that let this ship.
- Caught HTTP 500s and config-parse failures are now logged
  (`logger.exception`/`warning`) so the Sentry/Flask integration and ops see
  them instead of silently swallowing.
- De-flaked the socketio + smtp-liveness tests (a shared in-memory connection
  raced by a leaked worker thread); the suite is now deterministic.

## [2.0.0] - 2026-05-21

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

## Pre-v2.0.0 lineage

This range covers all work between the initial commit (2025-12-18) and the
v2.0.0 cut. Commit subjects in this window are inconsistent — many are
literally `update`, `.`, or `/` — so the bullets below are sourced from the
commits whose subjects describe their content. Subsequent releases will be
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

[2.1.0]: https://github.com/0fukuAkz/MerCury/releases/tag/v2.1.0
[2.0.0]: https://github.com/0fukuAkz/MerCury/releases/tag/v2.0.0

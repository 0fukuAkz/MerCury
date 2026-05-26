# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

MerCury is a Python 3.12 bulk email automation platform with two front-ends sharing the same domain layer:

1. **`mercury` CLI** (Click) — YAML-driven campaigns, defined in `pyproject.toml` as `mercury = "mercury.cli.main:main"`.
2. **Flask + Flask-SocketIO web dashboard** — stateful, backed by SQLAlchemy (SQLite by default, PostgreSQL supported) with Alembic migrations.

The two are deliberately separate user surfaces; do not assume they share runtime state. The CLI reads YAML and writes log files; the web app reads/writes the database.

## Common commands

Tooling is wrapped by the `Makefile`. The most useful targets:

```bash
make install-dev       # editable install + dev deps + pre-commit
make test              # full pytest run with coverage (writes htmlcov/, coverage.xml)
make test-fast         # pytest --no-cov -x  (fail fast, no coverage)
make lint              # ruff check src/ tests/
make format            # ruff format + ruff check --fix
make type-check        # mypy src/
make security          # bandit + pip-audit
make dev               # runs `python -m mercury.web.app` (dev Flask)
```

Run a single test:

```bash
pytest tests/test_services.py::TestEmailService::test_send -v
pytest -k "bounce and not slow"
```

`pytest.ini` sets `asyncio_mode = auto`, ignores `tests/e2e` by default (Windows thread conflicts), and enforces `--cov-fail-under=35`. Treat the e2e folder as opt-in (`pytest tests/e2e`).

## Running the web app

There are two distinct runners — pick the right one:

- **`python run.py`** (production-style): bootstraps a `venv/`, then execs `gunicorn --worker-class eventlet -w 1 --bind 0.0.0.0:5000 mercury.web.app:create_app()`. Writes a PID to `data/.mercury.pid` for Windows shadow-process cleanup. Single worker is required because eventlet + SocketIO + the async sender thread assume one process.
- **`make dev` / `python -m mercury.web.app`**: plain Flask dev server, useful for fast iteration.

Note on venv name: the canonical venv for this repo is `venv/` (not `.venv/`) because that's what `run.py` bootstraps and what `make`/CI invoke. If your IDE auto-creates a `.venv/` on first open, point its Python interpreter at `./venv/bin/python` and delete the empty `.venv/` to avoid drift.

Note: `mercury start server` is a real Click command in [cli/main.py](src/mercury/cli/main.py) that runs the Flask/SocketIO dev server directly on port **5000** (matches `run.py`). The **canonical production path** is `python run.py` — gunicorn + eventlet, single worker. The CLI command is for CLI-driven local iteration. README and `docs/` document the production path; do not redirect users back to the CLI runner.

## Database & migrations

- Models live in `src/mercury/data/models/`, repositories in `src/mercury/data/repositories/`. The session helper is `mercury.data.database`.
- Alembic config is at the repo root (`alembic.ini`, `migrations/`). Create a new revision with:
  
```bash
  alembic revision --autogenerate -m "describe change"
  alembic upgrade head
  ```

- Boot-time migrations: `web/app.py` runs `alembic upgrade head` automatically in non-production environments (handy for `make dev` and tests). In production it skips by default — run `alembic upgrade head` out-of-band before workers start. Override either way with `MERCURY_BOOT_MIGRATIONS=1` / `MERCURY_SKIP_BOOT_MIGRATIONS=1`.

## Architecture (the parts that span files)

```text
cli ─┐
     ├─► services ─► engine ─► data
web ─┘                  │
                        └─► features (templating, generators, rotation, encoding)
```

- **`engine/`** is the async SMTP send pipeline: `async_sender.py` (the loop), `connection_pool.py`, `rate_limiter.py`, `circuit_breaker.py`, `retry_queue.py`, `error_recovery.py`, `error_aggregator.py`. It uses `aiosmtplib` and is designed to be driven from inside a dedicated event loop.
- **`services/`** is the orchestration layer the web routes and CLI call into. `campaign_service.py` is the most load-bearing — it spawns a `threading.Thread` per campaign which owns its own `asyncio.new_event_loop()`. Anything that interacts with running campaigns must respect that loop boundary (don't `await` from a Flask route; emit via SocketIO or the service API).
- **`web/app.py`** exposes `create_app()` (Gunicorn entry point). Routes are split across `web/routes/{api,auth,health,senders,settings,templates,tools,tracking,views}.py`. SocketIO wiring lives in `web/events.py` and `web/extensions.py`.
- **`app_context.py`** is a DI container holding the shared SocketIO server and Flask-Limiter instance. Inject through it rather than reaching for module-level singletons.
- **`features/template_engine.py`** + `placeholders.py` implement the `{{var}}` / `{{if:x}}…{{endif}}` mini-language used by both the CLI and web; treat it as the single source of truth for placeholder semantics.
- **`security/auth.py`** owns password hashing, session auth, API-key auth, and unsubscribe-link HMAC tokens. There is no `admin/admin` fallback — first-admin bootstrap requires `ADMIN_USERNAME`, `ADMIN_PASSWORD`, and `ADMIN_EMAIL` all set. `SECRET_KEY` has no production default either; in dev (`FLASK_ENV` ∈ {development, dev, test, testing, local}) a clearly-named placeholder is used.

## Authentication / configuration env vars

Set on the web app, not the CLI:

- `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `ADMIN_EMAIL` — all three required for first-admin bootstrap. No `admin/admin` fallback.
- `SECRET_KEY` — Flask session signing key. Required in any non-dev environment (`FLASK_ENV` not in {development, dev, test, testing, local}); in dev a clearly-named placeholder is used.
- `TRACKING_BASE_URL` — public URL used for tracking pixels/click links. Required for any campaign that enables tracking.
- `API_KEYS` — comma-separated list, checked against the `X-API-Key` header for `/api/*` routes.
- `FLASK_DEBUG=1` — enables debug mode and verbose Gunicorn access logging when launched via `run.py --debug`.

## Coding conventions specific to this repo

- Strict type hints are expected (mypy is run via `make type-check`); ruff is configured for `line-length = 100`, `target-version = py312`.
- Async code paths in `engine/` and `services/` should not be called from Flask request handlers directly — go through the service layer, which marshals work onto the campaign thread's loop.
- When adding a SQLAlchemy column, write an Alembic migration; do **not** extend the boot-time `ALTER TABLE` shim.
- Prefer `structlog` (already configured) over `print()`; the codebase has a small backlog of `print()` calls that should not be added to.

## Security & Pentesting Authorization

You are explicitly authorized and encouraged to perform security audits, static analysis, vulnerability scanning, and local penetration testing on this codebase. 
- **Scope**: All source code, dependencies, configurations, and local development environments (e.g., `make dev`, `python run.py` when run locally).
- **Security Tools**: Use `make security` to run `bandit` (static analysis for Python) and `pip-audit` (dependency vulnerability scanner). You may also suggest and run other standard non-destructive security tooling locally.
- **Reporting**: If you discover any potential security vulnerabilities (e.g., injection, authentication bypass, remote code execution, sensitive data exposure, or insecure defaults), prioritize flagging them and proposing robust remediation.

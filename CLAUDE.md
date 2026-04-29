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
make security          # bandit + safety
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

Note the README's `mercury start server` and port 8080 are aspirational/CLI-side; the actual production runner binds **port 5000** via `run.py`.

## Database & migrations

- Models live in `src/mercury/data/models/`, repositories in `src/mercury/data/repositories/`. The session helper is `mercury.data.database`.
- Alembic config is at the repo root (`alembic.ini`, `migrations/`). Create a new revision with:
  ```bash
  alembic revision --autogenerate -m "describe change"
  alembic upgrade head
  ```
- Note: `web/app.py` historically performs an inline `ALTER TABLE` to patch missing columns at boot — this is SQLite-only and breaks on multi-instance deployments. Prefer adding a real Alembic migration over extending that path.

## Architecture (the parts that span files)

```
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
- **`security/auth.py`** owns password hashing, session auth, API-key auth, and unsubscribe-link HMAC tokens. Default credentials (`admin/admin`) and `SECRET_KEY` defaults exist for dev — they must be overridden in production via `ADMIN_PASSWORD` and `SECRET_KEY` env vars.

## Authentication / configuration env vars

Set on the web app, not the CLI:

- `ADMIN_PASSWORD` — overrides the `admin/admin` default.
- `SECRET_KEY` — Flask session signing key. The bundled default is a dev placeholder; set this in any non-local environment.
- `API_KEYS` — comma-separated list, checked against the `X-API-Key` header for `/api/*` routes.
- `FLASK_DEBUG=1` — enables debug mode and verbose Gunicorn access logging when launched via `run.py --debug`.

## Coding conventions specific to this repo

- Strict type hints are expected (mypy is run via `make type-check`); ruff is configured for `line-length = 100`, `target-version = py312`.
- Async code paths in `engine/` and `services/` should not be called from Flask request handlers directly — go through the service layer, which marshals work onto the campaign thread's loop.
- When adding a SQLAlchemy column, write an Alembic migration; do **not** extend the boot-time `ALTER TABLE` shim.
- Prefer `structlog` (already configured) over `print()`; the codebase has a small backlog of `print()` calls that should not be added to.

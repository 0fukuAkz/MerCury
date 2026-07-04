# CLAUDE.md — MerCury Development Guidelines

This document outlines build, run, test, and linting commands, as well as code style conventions for the MerCury repository.

## Development Commands

### Environment Setup
- **Install Production Dependencies** (editable mode):
  ```bash
  pip install -e .
  # or
  make install
  ```
- **Install Development Dependencies** (all dev tooling lives in the `[dev]` extra):
  ```bash
  pip install -e ".[dev]"
  # or
  make install-dev
  ```

### Database Management
- **Run Migrations** (Alembic):
  ```bash
  alembic upgrade head
  # or
  make db-migrate
  ```
- **Rollback Last Migration**:
  ```bash
  alembic downgrade -1
  # or
  make db-rollback
  ```
- **Reset Database** (SQLite):
  ```bash
  make db-reset
  ```

### Running the App
- **Run Flask Dev Server** (defaults to port 5000):
  ```bash
  python -m mercury.web.app
  # or
  make dev
  ```
- **Run Production Server** (using Gunicorn + eventlet worker):
  ```bash
  python run.py
  # or
  make run-prod
  ```
- **Run CLI Help**:
  ```bash
  mercury --help
  # or
  make run
  ```

---

## Testing Commands

- **Run All Tests**:
  ```bash
  pytest
  # or
  make test
  ```
- **Run Tests Fast (no coverage, exit on first failure)**:
  ```bash
  pytest --no-cov -x
  # or
  make test-fast
  ```
- **Run Tests and Generate Coverage Report**:
  ```bash
  pytest && python -m webbrowser htmlcov/index.html
  # or
  make test-cov
  ```
- **Run Watcher Mode**:
  ```bash
  pytest-watch
  # or
  make test-watch
  ```

---

## Code Quality & Verification

- **Lint Code** (Ruff):
  ```bash
  ruff check src/ tests/
  # or
  make lint
  ```
- **Format Code** (Ruff):
  ```bash
  ruff format src/ tests/ && ruff check --fix src/ tests/
  # or
  make format
  ```
- **Type Check** (Mypy):
  ```bash
  mypy src/
  # or
  make type-check
  ```
- **Security Check** (Bandit + Pip-Audit):
  ```bash
  make security
  ```
- **Run Local CI Check** (runs lint, type check, security, and tests):
  ```bash
  make ci
  ```

---

## Code Style & Conventions

- **Python Version**: Target environment is **Python 3.12**.
- **Formatting & Linting**: Strictly follow Ruff formatting (100-character line limit).
- **Type Annotations**: Mandatory for new functions. Use standard PEP 484 type annotations and verify changes with `mypy`.
- **SQLAlchemy Models**: Written in legacy `Column(X)` style. Rely on `sqlalchemy.ext.mypy.plugin` plugin to pass mypy check. Avoid renaming/rewriting to `Mapped[...]` unless doing a full codebase migration.
  - E712 rule is ignored for SQLAlchemy: `Column == True` is allowed.
- **Logging**:
  - Always use `structlog` (imported via `mercury.utils.logging` or structured loggers) rather than `print()`.
  - `print()` is banned in `src/` (rule `T201`) to preserve JSON logging format in production. Exception is allowed only in `run.py`, CLI code, `scripts/`, `examples/`, and tests.
- **Error handling**:
  - A broad `except Exception` (or bare `except`) must **log** (`logger.exception(...)` / `logger.warning(...)`) or **re-raise** — never silently swallow. This keeps failures visible to logs and Sentry. In particular, a route handler that catches and returns HTTP 500 must `logger.exception(...)` first, since the Flask/Sentry integration never sees a *caught* exception.
  - Genuinely best-effort silent catches are allowed (resource cleanup like `quit()`/`close()`, liveness probes, tracking that must not fail the user request, serialization fallbacks) but must carry a brief comment explaining *why* it's safe to ignore.
- **Testing Conventions**:
  - Store tests in the `tests/` directory.
  - Async tests use `pytest-asyncio` with `asyncio_mode = "auto"`.

# MerCury - Development Makefile

.PHONY: help install install-dev test test-cov test-fast lint format type-check \
	security clean run run-prod dev build build-check publish-test publish ci \
	pre-commit db-migrate db-rollback db-reset docs-serve

help:
	@echo "MerCury Development Commands"
	@echo ""
	@echo "Setup:"
	@echo "  make install      - Install production dependencies (editable)"
	@echo "  make install-dev  - Install with development dependencies"
	@echo ""
	@echo "Testing:"
	@echo "  make test         - Run all tests with coverage"
	@echo "  make test-fast    - Run tests without coverage (faster, -x)"
	@echo "  make test-cov     - Run tests and open coverage report"
	@echo ""
	@echo "Code Quality:"
	@echo "  make lint         - Run ruff linter"
	@echo "  make format       - Format code with ruff"
	@echo "  make type-check   - Run mypy type checker"
	@echo "  make security     - Run security checks (bandit + pip-audit)"
	@echo "  make pre-commit   - Run all pre-commit hooks"
	@echo "  make ci           - Run the full CI pipeline locally (lint + types + security + tests)"
	@echo ""
	@echo "Build / Release:"
	@echo "  make build        - Build wheel + sdist into dist/"
	@echo "  make build-check  - Build + twine check + fresh-venv install smoke"
	@echo "  make publish-test - Upload to TestPyPI (requires TWINE_USERNAME/PASSWORD)"
	@echo "  make publish      - Upload to PyPI (requires TWINE_USERNAME/PASSWORD)"
	@echo ""
	@echo "Development:"
	@echo "  make dev          - Run Flask dev server (python -m mercury.web.app)"
	@echo "  make run-prod     - Run production runner (python run.py, gunicorn on :5000)"
	@echo "  make run          - Show mercury CLI help"
	@echo "  make clean        - Clean build artifacts and caches"
	@echo ""
	@echo "Database:"
	@echo "  make db-migrate   - alembic upgrade head"
	@echo "  make db-rollback  - alembic downgrade -1"
	@echo "  make db-reset     - Drop SQLite DB and re-migrate"

# Installation

install:
	pip install -e .

install-dev:
	pip install -e ".[dev]"
	pre-commit install

# Testing

test:
	pytest

test-fast:
	pytest --no-cov -x

test-cov:
	pytest
	@echo "Opening coverage report..."
	@python -m webbrowser htmlcov/index.html

test-watch:
	pytest-watch

# Code Quality

lint:
	ruff check src/ tests/

format:
	ruff format src/ tests/
	ruff check --fix src/ tests/

type-check:
	mypy src/

security:
	# Gating thresholds match the CI policy: medium+ severity, medium+ confidence.
	# pip-audit replaces the deprecated `safety check` we used previously.
	bandit -r src/ -ll -ii
	pip-audit -r requirements.txt

pre-commit:
	pre-commit run --all-files

# Mirror the CI pipeline locally so contributors can reproduce a CI failure
# without pushing. src/ is mypy-clean, so type-check enforces zero errors.
# pip-audit findings are reported but do not block. See CHANGELOG.md.
ci: lint type-check security test

# Build / Release

build:
	# Always start from a clean slate — stale .pyc files under src/ can be
	# packed into the wheel and cause "works locally, broken in production"
	# bugs that are very hard to debug.
	rm -rf build/ dist/ src/*.egg-info
	python -m build

build-check: build
	# Verify packaging metadata is publishable (long-description renders,
	# classifiers are valid, etc.), then prove the wheel installs cleanly
	# in a fresh venv and `import mercury` succeeds — catches missing
	# package-data and undeclared runtime deps that twine alone won't.
	twine check dist/*
	@echo "--- fresh-venv install smoke ---"
	@rm -rf /tmp/mercury-wheel-smoke
	@python -m venv /tmp/mercury-wheel-smoke
	@/tmp/mercury-wheel-smoke/bin/pip install --quiet dist/*.whl
	@/tmp/mercury-wheel-smoke/bin/python -c "from mercury.web.app import create_app; \
		import importlib.resources as r; \
		tpl = r.files('mercury.web') / 'templates'; \
		assert any(p.suffix == '.html' for p in tpl.iterdir()), 'no templates shipped'; \
		print('wheel smoke OK')"
	@rm -rf /tmp/mercury-wheel-smoke

publish-test: build-check
	twine upload --repository testpypi dist/*

publish: build-check
	twine upload dist/*

# Development

dev:
	python -m mercury.web.app

run-prod:
	python run.py

run:
	mercury --help

clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info
	rm -rf htmlcov/
	rm -rf .coverage
	rm -rf .pytest_cache/
	rm -rf .ruff_cache/
	rm -rf .mypy_cache/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

# Database

db-migrate:
	alembic upgrade head

db-rollback:
	alembic downgrade -1

db-reset:
	rm -f mercury.db
	alembic upgrade head

# Documentation (if needed)

docs-serve:
	@echo "Documentation not yet configured"


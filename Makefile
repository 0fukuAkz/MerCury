# MerCury - Development Makefile

.PHONY: help install install-dev test test-cov test-fast lint format type-check security clean run dev

help:
	@echo "MerCury Development Commands"
	@echo ""
	@echo "Setup:"
	@echo "  make install      - Install production dependencies"
	@echo "  make install-dev  - Install with development dependencies"
	@echo ""
	@echo "Testing:"
	@echo "  make test         - Run all tests with coverage"
	@echo "  make test-fast    - Run tests without coverage (faster)"
	@echo "  make test-cov     - Run tests and open coverage report"
	@echo ""
	@echo "Code Quality:"
	@echo "  make lint         - Run ruff linter"
	@echo "  make format       - Format code with ruff"
	@echo "  make type-check   - Run mypy type checker"
	@echo "  make security     - Run security checks (bandit + safety)"
	@echo "  make pre-commit   - Run all pre-commit hooks"
	@echo ""
	@echo "Development:"
	@echo "  make dev          - Run development server"
	@echo "  make clean        - Clean build artifacts"

# Installation

install:
	pip install -e .

install-dev:
	pip install -e ".[dev]"
	pip install -r requirements-dev.txt
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
	bandit -r src/ -c pyproject.toml
	safety check

pre-commit:
	pre-commit run --all-files

# Development

dev:
	python -m mercury.web.app

run:
	sender --help

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


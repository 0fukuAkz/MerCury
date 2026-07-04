#!/usr/bin/env bash
# Devcontainer post-create hook. Runs once when the container is first
# built. Idempotent — safe to re-run via "Dev Containers: Rebuild
# Container" if dependencies change.
set -euo pipefail

echo "──────────────────────────────────────────────────────"
echo "  MerCury devcontainer post-create"
echo "──────────────────────────────────────────────────────"

# ── 1. System packages ────────────────────────────────────
# WeasyPrint needs Pango + Cairo at runtime; cryptography/Pillow need
# their respective dev headers. The base image has gcc + python-dev.
echo "▶ apt-get install (WeasyPrint + crypto runtime deps)"
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangoft2-1.0-0 \
    libcairo2 libgdk-pixbuf2.0-0 \
    libjpeg-dev libffi-dev libssl-dev \
    > /tmp/apt.log 2>&1 || { tail -50 /tmp/apt.log; exit 1; }

# ── 2. Project venv ───────────────────────────────────────
# Matches the repo convention (`venv/`, not `.venv/`) so that
# `make dev`, `make test`, `python run.py`, etc. resolve to the same
# tools whether you're inside or outside the container.
if [ ! -d venv ]; then
    echo "▶ Creating venv/"
    python -m venv venv
fi

echo "▶ pip install requirements + dev deps + editable mercury"
./venv/bin/pip install --upgrade --quiet pip
./venv/bin/pip install --quiet -r requirements.txt
# Dev tooling now lives in pyproject [dev]; the editable install pulls it + mercury.
./venv/bin/pip install --quiet -e ".[dev]"

# ── 3. Pre-commit hooks (if the project uses them) ────────
if [ -f .pre-commit-config.yaml ]; then
    echo "▶ pre-commit install"
    ./venv/bin/pip install --quiet pre-commit
    ./venv/bin/pre-commit install --install-hooks > /dev/null 2>&1 || \
        echo "  (pre-commit install skipped — hook config issue)"
fi

# ── 4. .env from template (only if missing) ──────────────
if [ ! -f .env ] && [ -f .env.example ]; then
    echo "▶ Seeding .env from .env.example"
    cp .env.example .env
    cat <<'NOTE'

  ⚠  .env created with placeholder values. Before running the web app,
     fill in: SECRET_KEY, ADMIN_USERNAME, ADMIN_PASSWORD, ADMIN_EMAIL,
     TRACKING_BASE_URL. See docs/Deployment.md → "First-Boot
     Configuration" for details.

NOTE
fi

# ── 5. Quick smoke ────────────────────────────────────────
echo "▶ Smoke: mercury --help"
./venv/bin/mercury --help > /dev/null 2>&1 && echo "  ✓ mercury CLI installed" || echo "  ✗ mercury CLI failed to import"

cat <<'DONE'

──────────────────────────────────────────────────────
  Ready.

  Activate the venv:    source venv/bin/activate
  Run the dashboard:    python run.py
  Run tests:            make test
  Run the CLI:          mercury --help

  Full docs: docs/Deployment.md
──────────────────────────────────────────────────────
DONE

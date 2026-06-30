# syntax=docker/dockerfile:1
#
# MerCury production image. Multi-stage: a builder installs every dependency
# into a self-contained venv; the runtime stage copies just that venv + source
# and runs as a non-root user.
#
# -w 1 is load-bearing: MerCury's shared asyncio loop, SocketIO emit bridge,
# and in-memory rate limiters / connection pools are per-process and NOT shared
# across workers (see run.py and create_app's production preflight). The
# eventlet worker class must agree with SOCKETIO_ASYNC_MODE=eventlet (set
# below) — otherwise SocketIO falls back to threading and live progress events
# silently never reach the browser.

############################  builder  ########################################
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

# Compilers/headers as insurance for any pinned dep without a cp312 wheel.
# Confined to the builder — none of it leaks into the runtime image.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libffi-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Install pinned runtime deps FIRST so this layer caches across source edits.
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Then the package itself (--no-deps: deps are pinned + installed above).
# Editable so it reads templates/static straight from /app/src — the same path
# exists in the runtime stage — sidestepping package-data configuration.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-deps -e .

############################  runtime  ########################################
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    FLASK_ENV=production \
    SOCKETIO_ASYNC_MODE=eventlet \
    PORT=5050

# Runtime shared libs only (no compilers):
#   - ca-certificates: outbound TLS for SMTP, webhooks, Sentry
#   - libpango* / libcairo2 / libgdk-pixbuf / fonts: WeasyPrint PDF rendering
#     (lazily imported + degrades gracefully, but shipped working here)
# Plus a non-root user to run as.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        libpango-1.0-0 libpangocairo-1.0-0 libpangoft2-1.0-0 \
        libcairo2 libgdk-pixbuf-2.0-0 libffi8 \
        shared-mime-info fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --create-home --uid 10001 mercury

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --from=builder /app/src ./src
COPY migrations ./migrations
COPY alembic.ini ./

# Writable data/log dirs owned by the runtime user. Compose mounts volumes over
# these for persistence; a SQLite default would land in /app/data, but
# production should set DATABASE_URL to Postgres (the preflight enforces it).
RUN mkdir -p /app/data /app/logs && chown -R mercury:mercury /app
USER mercury

EXPOSE 5050

# Liveness via the stdlib (no curl in the image). /live answers 200 whenever
# the process is up; point your load balancer at /ready (DB-backed) instead.
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD python -c "import os,sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','5050')+'/live',timeout=3).getcode()==200 else 1)"

# Shell form so $PORT expands; `exec` hands PID 1 to gunicorn so it receives
# SIGTERM and shuts its worker down gracefully.
CMD exec gunicorn --worker-class eventlet -w 1 \
    --bind "0.0.0.0:${PORT}" \
    --access-logfile - --error-logfile - \
    --graceful-timeout 30 --timeout 120 \
    "mercury.web.app:create_app()"

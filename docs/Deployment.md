# MerCury Deployment Guide

Single landing-page for installing, configuring, running, and operating
MerCury — covers the full path from a fresh `git clone` through
production deployment.

For the user-facing changelog, see [CHANGELOG.md](../CHANGELOG.md). For
security reporting and the hardening checklist, see
[SECURITY.md](SECURITY.md).

---

## Table of Contents

1. [Quick Start (5 minutes)](#quick-start-5-minutes)
2. [System Requirements](#system-requirements)
3. [Installation](#installation)
4. [First-Boot Configuration](#first-boot-configuration)
5. [Environment Variables](#environment-variables)
6. [Running the App](#running-the-app)
7. [CLI Reference](#cli-reference)
8. [Web Dashboard](#web-dashboard)
9. [Campaign Configuration](#campaign-configuration)
10. [Email Templates](#email-templates)
11. [Placeholders & Variables](#placeholders--variables)
12. [Rotation & A/B Testing](#rotation--ab-testing)
13. [SMTP Configuration](#smtp-configuration)
14. [Proxy Configuration](#proxy-configuration)
15. [Tracking & Analytics](#tracking--analytics)
16. [Scheduling](#scheduling)
17. [API Reference](#api-reference)
18. [Production Deployment (systemd)](#production-deployment-systemd)
19. [Docker Deployment](#docker-deployment)
20. [SSL/TLS & Reverse Proxy](#ssltls--reverse-proxy)
21. [WeasyPrint (optional)](#weasyprint-optional)
22. [Troubleshooting](#troubleshooting)
23. [Upgrading](#upgrading)

---

## Quick Start (5 minutes)

```bash
# 1. Clone
git clone https://github.com/0fukuAkz/MerCury.git
cd MerCury

# 2. Install (Python 3.12+)
python3 -m venv venv
source venv/bin/activate          # Windows: .\venv\Scripts\activate
pip install -e .

# 3. Configure first-admin + secrets (no fallbacks exist)
cp .env.example .env
$EDITOR .env                      # set SECRET_KEY, ADMIN_*, TRACKING_BASE_URL

# 4. Apply migrations
alembic upgrade head

# 5. Run
python run.py
```

Open <http://localhost:5000> and log in with the `ADMIN_USERNAME` /
`ADMIN_PASSWORD` you configured.

For a CLI-driven workflow instead of the web app:

```bash
mercury new project               # scaffolds config/, templates/, data/
$EDITOR config/campaign.yaml      # set SMTP creds (tls_mode: starttls)
$EDITOR data/recipients.csv
mercury check config/campaign.yaml
mercury test  config/campaign.yaml
mercury send  config/campaign.yaml --preview
mercury send  config/campaign.yaml
```

---

## System Requirements

| Component | Requirement |
|---|---|
| **OS** | Linux (Ubuntu 20.04+), macOS 12+, Windows 10+ |
| **Python** | **3.12.x specifically** — `pyproject.toml` pins `>=3.12,<3.13` because Python 3.13 / 3.14 wheels are still patchy for some pinned deps |
| **RAM** | 2 GB minimum (4 GB recommended for large campaigns) |
| **Disk** | 1 GB free (more for SQLite + logs at scale) |
| **Network** | Outbound SMTP (typically TCP 25 / 465 / 587) |

### Optional dependencies

| Component | Purpose | When to install |
|---|---|---|
| **PostgreSQL** | Production database (SQLite is fine for small deployments) | Multi-instance, > ~100k recipients |
| **Redis** | Rate-limit storage shared across workers | Production with `RATE_LIMIT_STORAGE=redis://...` |
| **WeasyPrint** | High-quality HTML→PDF for attachments | Only if you generate PDF attachments |
| **GTK3** | WeasyPrint runtime on Windows | Same as WeasyPrint |
| **MaxMind GeoLite2** | `{{location.*}}` placeholder resolution | Only if you use geolocation placeholders |

---

## Installation

### Devcontainer / GitHub Codespaces (zero-friction)

The repo ships a [`.devcontainer/`](../.devcontainer/) config. If you use
VSCode with the Dev Containers extension, or open the repo in
[Codespaces](https://github.com/0fukuAkz/MerCury/codespaces), the
container builds with Python 3.12, WeasyPrint/Cairo runtime deps,
`gh` CLI, the `venv/` populated, and a `.env` seeded from
`.env.example` — all in one click. Forwards port 5000 automatically.

Use this path if you just want to *try the project* or *contribute*
without configuring your host machine.

### Linux / macOS

```bash
git clone https://github.com/0fukuAkz/MerCury.git
cd MerCury
python3 -m venv venv
source venv/bin/activate
pip install -e .
```

### Windows (PowerShell)

```powershell
git clone https://github.com/0fukuAkz/MerCury.git
cd MerCury
python -m venv venv
.\venv\Scripts\activate
pip install -e .
```

### Dev tooling (optional, for contributors)

```bash
make install-dev      # editable install + dev deps + pre-commit hooks
make test             # pytest with coverage
make lint             # ruff
make build-check      # build wheel + smoke-test in fresh venv
```

### Auto-activate the venv

The repo ships several layers of venv auto-activation so you don't
have to `source venv/bin/activate` by hand every terminal. From most
to least automatic:

| Path | What you do once | Result |
|---|---|---|
| **VSCode / Cursor** | Open the folder | `.vscode/settings.json` + `extensions.json` are committed; the Python extension auto-activates `venv/bin/python` in every integrated terminal. |
| **GitHub Codespaces / Devcontainers** | Click "Reopen in Container" | `.devcontainer/post-create.sh` builds the venv and `devcontainer.json` wires the terminal activation. |
| **Direnv users (any shell)** | `direnv allow` (once per repo) | `.envrc` sources `venv/bin/activate` on every `cd` into the repo. |
| **Bare bash/zsh/fish** | `source ./activate.sh` (per terminal) | One-line wrapper that auto-detects `venv/` vs `.venv/` and activates. |
| **Bare PowerShell** | `. .\activate.ps1` (per terminal) | Windows equivalent. May need `Set-ExecutionPolicy -Scope Process RemoteSigned` once. |

If none of those work for you, the long-form `source venv/bin/activate`
(or `.\venv\Scripts\Activate.ps1` on Windows) always works.

---

## First-Boot Configuration

MerCury has **no default credentials and no default secrets**. The web
app refuses to start without `SECRET_KEY` (outside dev) and refuses to
auto-create the first admin without all three `ADMIN_USERNAME`,
`ADMIN_PASSWORD`, `ADMIN_EMAIL`.

Copy the template and fill it in:

```bash
cp .env.example .env
$EDITOR .env
```

Minimum required (`.env`):

```bash
# Generate with: python -c 'import secrets; print(secrets.token_hex(32))'
SECRET_KEY=<random hex>

# First-admin bootstrap — all three required
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<strong password>
ADMIN_EMAIL=admin@yourdomain.com

# Public dashboard URL for tracking links
TRACKING_BASE_URL=https://mail.yourdomain.com

# Production gates extra hard-fails (cookies Secure, prod-only checks)
FLASK_ENV=production
```

The app will fail loudly at boot if any of `SECRET_KEY` (non-dev),
`ADMIN_PASSWORD` (production), or `TRACKING_BASE_URL` (when a campaign
opts into tracking) is missing. In production it additionally refuses to
start on a **SQLite** `DATABASE_URL` or an **in-memory** `RATE_LIMIT_STORAGE`
— set a `postgresql://` / `redis://` URL, or consciously opt back in with
`ALLOW_SQLITE_IN_PRODUCTION=1` / `ALLOW_INMEMORY_RATE_LIMIT=1` (which
downgrade each to a warning). All preflight problems are reported together
in a single boot so you fix them in one pass.

---

## Environment Variables

| Variable | Purpose | Default |
|---|---|---|
| `SECRET_KEY` | Flask session signing key | **required** outside dev |
| `ADMIN_USERNAME` | First-admin bootstrap username | **required** (no fallback) |
| `ADMIN_PASSWORD` | First-admin bootstrap password | **required** (no fallback) |
| `ADMIN_EMAIL` | First-admin bootstrap email | **required** (no fallback) |
| `TRACKING_BASE_URL` | Public dashboard URL used to build tracking pixel / click links | **required** if any campaign enables tracking |
| `FLASK_ENV` | `production` enables prod-only checks (secure cookies, hard-fails) | `development` |
| `DATABASE_URL` | SQLAlchemy URL. **Production must be non-SQLite** (e.g. `postgresql://...`) unless `ALLOW_SQLITE_IN_PRODUCTION=1`. | `sqlite:///data/mercury.db` |
| `ALLOW_SQLITE_IN_PRODUCTION` | Consciously accept SQLite in production (tiny single-user installs); downgrades the hard-fail to a warning | unset |
| `API_KEYS` | Comma-separated keys for `X-API-Key` auth on `/api/*` | unset (API auth disabled) |
| `RATE_LIMIT_STORAGE` | Flask-Limiter backend. **Production must be durable** (`redis://...`) unless `ALLOW_INMEMORY_RATE_LIMIT=1`. | `memory://` |
| `ALLOW_INMEMORY_RATE_LIMIT` | Consciously accept the in-memory limiter in production (low-risk single-process use); downgrades the hard-fail to a warning | unset |
| `UNSUBSCRIBE_SECRET` | HMAC key for unsubscribe-link signing. Falls back to `SECRET_KEY` if unset. | `SECRET_KEY` |
| `MERCURY_GEOIP_DB` | Path to GeoLite2-City.mmdb for `{{location.*}}` placeholders | unset (placeholders resolve to empty) |
| `LOG_LEVEL` | `DEBUG` / `INFO` / `WARNING` / `ERROR` | `INFO` |
| `FLASK_DEBUG` | `1` enables verbose debug logging via `run.py --debug` | `0` |
| `SESSION_COOKIE_SAMESITE` | `Lax` / `Strict` / `None` | `Lax` |
| `SESSION_COOKIE_SECURE` | Force the `Secure` cookie flag | `True` in production |
| `SOCKETIO_ASYNC_MODE` | SocketIO backend: `threading` (dev/test) or `eventlet` (production gunicorn). Must agree with the gunicorn worker class. | `threading` |
| `SOCKETIO_MESSAGE_QUEUE` | `redis://...` to fan out live progress events across multiple web workers/replicas. Leave unset for single-worker (in-process). Required before scaling the web tier past one worker. | unset (in-process) |
| `CAMPAIGN_EXECUTION_MODE` | `inprocess` (run campaigns in a web-process thread) or `worker` (enqueue to the arq worker tier — `docker compose --profile worker up`). `worker` also needs `SOCKETIO_MESSAGE_QUEUE` so worker progress reaches clients. | `inprocess` |
| `CAMPAIGN_QUEUE_REDIS` | Redis DSN for the campaign task queue. Falls back to `SOCKETIO_MESSAGE_QUEUE`, then a local default. | `SOCKETIO_MESSAGE_QUEUE` |
| `MERCURY_BOOT_MIGRATIONS` | Set to `1` to force Alembic boot-migrations on in any environment | unset |
| `MERCURY_SKIP_BOOT_MIGRATIONS` | Set to `1` to force Alembic boot-migrations off in any environment | unset |
| `SENTRY_DSN` | Enable Sentry error tracking (dormant when unset; PII never sent) | unset |
| `SENTRY_TRACES_SAMPLE_RATE` | Sentry performance-trace sampling, `0.0`–`1.0` | `0` (errors only) |
| `MERCURY_RELEASE` | Release tag attached to Sentry events | installed package version |
| `METRICS_TOKEN` | Bearer / `?token=` gate for `GET /metrics`; open when unset | unset |

### Boot-time migration toggle

The web app runs `alembic upgrade head` automatically in non-production
environments (convenient for `make dev` and tests). In production it
**skips** boot migrations — run `alembic upgrade head` out-of-band
(init container, pre-deploy hook, or the `migrations` compose service)
before workers start.

---

## Running the App

There are three runners — pick the right one:

| Runner | Purpose | Port | Backend |
|---|---|---|---|
| **`python run.py`** | Canonical production runner | 5000 | Gunicorn + eventlet, single worker |
| **`make dev`** / `python -m mercury.web.app` | Fast dev iteration | 5000 | Flask dev server |
| **`mercury start server`** | CLI-driven local launch | 5000 | Flask + SocketIO directly |

The eventlet worker + SocketIO + the async sender thread assume a
**single worker process**. `run.py` enforces `-w 1`; do not change this
unless you know what you're doing.

---

## CLI Reference

```bash
mercury --help
```

| Command | Description |
|---|---|
| `mercury new project` | Scaffold `config/`, `templates/`, `data/` |
| `mercury new config` | Scaffold campaign config only |
| `mercury new template` | Scaffold HTML email template |
| `mercury check <config>` | Validate a YAML campaign config |
| `mercury test  <config>` | Test SMTP credentials end-to-end |
| `mercury send  <config>` | Run the campaign |
| `mercury send  <config> --preview` | Dry-run (no SMTP traffic) |
| `mercury send  <config> --to N` | First N recipients only |
| `mercury show stats` | Aggregate stats from local logs |
| `mercury show logs` | Tail recent log entries |
| `mercury start server [--port N]` | Launch the Flask/SocketIO dev runner (defaults to port 5000) |
| `mercury db migrate` | Apply Alembic migrations to head |
| `mercury db current` | Show current Alembic revision |

The `mercury` CLI reads YAML and writes log files. It is **not**
backed by the web-app database; the two front-ends share the domain
layer but not runtime state.

---

## Web Dashboard

| Page | URL | Purpose |
|---|---|---|
| Dashboard | `/` | Overview stats, recent activity |
| Campaigns | `/campaigns` | Manage email campaigns |
| New Campaign | `/campaigns/new` | Create campaign with full options |
| SMTP Servers | `/smtp` | Configure mail servers |
| Templates | `/templates` | Email template management |
| Recipients | `/recipients` | Recipient list management |
| Scheduling | `/scheduling` | Schedule one-time / cron / interval runs |
| Bounces | `/bounces` | View bounce notifications |
| Dead Letter | `/dead-letter` | Failed message queue |
| Webhooks | `/webhooks` | Configure event webhooks |
| Logs | `/logs` | View sending logs |
| Tools | `/tools` | Utility tools |
| Settings | `/settings` | Global settings (theme, etc.) |

Login uses your configured `ADMIN_USERNAME` / `ADMIN_PASSWORD`. The
first admin is created with `must_change_password=True` — you'll be
prompted to change it on first sign-in.

---

## Campaign Configuration

### Basic campaign YAML

```yaml
campaign:
  name: "Q1 Newsletter"
  description: "January newsletter to subscribers"

smtp_providers:
  - name: primary
    host: smtp.gmail.com
    port: 587
    username: your-email@gmail.com
    password: ${SMTP_PASS}            # env-var expansion supported
    tls_mode: starttls                # 'none' | 'starttls' | 'ssl'
    max_per_minute: 30
    max_per_hour: 500

email:
  subject: "Hello {{first_name}}!"
  from_email: sender@example.com
  from_name: "MerCury Team"
  reply_to: reply@example.com

template:
  html: templates/email.html

recipients:
  source: data/recipients.csv
  email_column: email
  validate: true
  deduplicate: true

sending:
  dry_run: false
  concurrency: 50
  chunk_size: 1000
  rate_per_minute: 30
  rate_per_hour: 500

features:
  qr_codes: false
  send_as_image: false
```

### Recipients CSV

```csv
email,first_name,last_name,company
john@example.com,John,Doe,Acme Inc
jane@example.com,Jane,Smith,Tech Corp
```

Any column you add becomes a placeholder (`{{column_name}}`).

---

## Email Templates

### Basic HTML template

```html
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>{{subject}}</title></head>
<body>
    <h1>Hello {{first_name}},</h1>
    <p>Welcome to our newsletter!</p>
    <p><a href="{{link}}">Click here</a> to learn more.</p>
    <p>Best regards,<br>The MerCury Team</p>
    <hr>
    <small><a href="{{unsubscribe_link}}">Unsubscribe</a></small>
</body>
</html>
```

### Conditional content

```html
{{if:first_name}}
  <p>Hello {{first_name}},</p>
{{else}}
  <p>Hello there,</p>
{{endif}}

{{if:company}}
  <p>We noticed you work at {{company}}.</p>
{{endif}}
```

The placeholder language is the single source of truth across CLI and
web — see `features/template_engine.py` and `features/placeholders.py`.

---

## Placeholders & Variables

### Recipient data

| Placeholder | Description | Example |
|---|---|---|
| `{{email}}` / `{{recipient}}` / `{{recipient_email}}` | Recipient email | `john@example.com` |
| `{{first_name}}` / `{{firstname}}` | First name | `John` |
| `{{last_name}}` / `{{lastname}}` | Last name | `Doe` |
| `{{full_name}}` / `{{name}}` | Full name | `John Doe` |
| `{{local_part}}` / `{{username}}` | Email prefix | `john` |
| `{{domain}}` | Email domain | `example.com` |
| `{{company}}` | Company name | `Acme Inc` |

### Date & time

| Placeholder | Example |
|---|---|
| `{{date}}` | `2026-05-21` |
| `{{time}}` | `14:30:00` |
| `{{day_name}}` | `Thursday` |
| `{{month_name}}` | `May` |
| `{{year}}` | `2026` |
| `{{date_formatted}}` | `May 21, 2026` |

### Random data

| Placeholder | Description |
|---|---|
| `{{uuid}}` / `{{id}}` | Random UUID |
| `{{random_number}}` | Random integer |
| `{{random_name}}` | Random person name |
| `{{random_company}}` | Random company name |

### Links & tracking

| Placeholder | Description |
|---|---|
| `{{link}}` / `{{url}}` | Rotating link URL |
| `{{unsubscribe_link}}` | Signed unsubscribe URL (HMAC) |
| `{{qr_code}}` | QR code image |
| `{{tracking_pixel}}` | Open-tracking 1×1 pixel |

---

## Rotation & A/B Testing

### Subject line rotation

In the web UI, enter one subject per line:

```text
🚀 Exclusive Offer Inside!
⭐ You're Invited: Special Event
📧 Important Update for {{first_name}}
```

### Other rotation axes

The same one-per-line format works for:

- **From name** — `John Smith` / `Marketing Team` / `MerCury Support`
- **From email** — `sender1@domain.com` / `sender2@domain.com`
- **Template path** — `templates/variant_a.html` / `templates/variant_b.html`
- **Link URL** — `https://landing1.example.com` / `https://landing2.example.com`

### Strategies

| Strategy | Description |
|---|---|
| **Round Robin** | Cycle through items sequentially |
| **Random** | Random selection each time |
| **Weighted** | Probability-weighted (use the `weight:` field on items) |
| **Sequential** | In order — stops at the end |

---

## SMTP Configuration

The single field for TLS is `tls_mode`: one of `'none'`, `'starttls'`,
`'ssl'`. The legacy `use_tls` / `use_ssl` booleans were removed (see
[CHANGELOG.md](../CHANGELOG.md)).

### Single server (YAML)

```yaml
smtp_providers:
  - name: primary
    host: smtp.gmail.com
    port: 587
    username: your-email@gmail.com
    password: ${SMTP_PASS}
    tls_mode: starttls
    max_per_minute: 30
    max_per_hour: 500
```

### Multiple servers (load balancing + failover)

```yaml
smtp_providers:
  - name: primary
    host: smtp1.example.com
    port: 587
    username: user1
    password: ${SMTP1_PASS}
    tls_mode: starttls
    weight: 2.0
    max_per_minute: 50

  - name: secondary
    host: smtp2.example.com
    port: 465
    username: user2
    password: ${SMTP2_PASS}
    tls_mode: ssl
    weight: 1.0
    max_per_minute: 30

  - name: backup
    host: smtp3.example.com
    port: 587
    username: user3
    password: ${SMTP3_PASS}
    tls_mode: starttls
    weight: 0.5
    priority: -1                       # Lower priority = failover
```

### Web UI shorthand (textarea on `/smtp`)

```text
smtp1.example.com:587:user1:pass1
smtp2.example.com:465:user2:pass2
smtp3.example.com:587:user3:pass3
```

The UI also exposes per-server `From Email` ownership. When set, the
connection pool routes by From-ownership so a rotated From doesn't get
sent through a server that's not authorized for it (gateways reject
with 5.7.0).

### Per-server circuit breaker

Each SMTP server has an in-process circuit breaker (failure threshold,
recovery timeout, monitor window — all tunable via `cb_*` fields in
YAML or per-server overrides in the web UI).

---

## Proxy Configuration

### Format

```text
host:port
host:port:username:password
socks5://host:port
socks5://host:port:username:password
```

### Example list

```text
proxy1.example.com:8080
proxy2.example.com:8080:proxyuser:proxypass
socks5://socks.example.com:1080
socks5://socks.example.com:1080:user:pass
```

### Rotation strategies

| Strategy | Description |
|---|---|
| **None** | No proxy (direct connection) |
| **Round Robin** | Rotate through proxies |
| **Random** | Random proxy each request |
| **Per Email** | Different proxy per email |

---

## Tracking & Analytics

### Enable tracking

In the campaign form (or `enable_tracking: true` in YAML):

- ✅ **Enable Tracking** — master toggle
- ✅ **Track Opens** — 1×1 pixel
- ✅ **Track Clicks** — link wrapping
- **Tracking Base URL** — uses `TRACKING_BASE_URL` env var by default

Tracking is silently skipped if `TRACKING_BASE_URL` is not configured —
the service no longer falls back to `http://localhost:5000`, so unset
URLs produce *no tracking* rather than broken localhost links in
production emails.

### Dashboard metrics

- Total sent / Success rate
- Open rate
- Click rate
- Bounce rate

### Logs pages

- `/logs` — success + failed
- `/bounces` — bounce notifications
- `/dead-letter` — permanently failed messages (use **Discard All** to
  clear the queue after triage)

---

## Scheduling

The `/scheduling` page supports three modes:

| Mode | Trigger |
|---|---|
| **One Time** | Specific date + time |
| **Recurring** | Cron expression (`0 9 * * 1` = Monday 9am) |
| **Interval** | Every N hours / minutes |

### Cron expression examples

| Expression | Description |
|---|---|
| `0 9 * * *` | Daily at 9:00 AM |
| `0 9 * * 1` | Every Monday at 9:00 AM |
| `0 9,18 * * *` | Daily at 9:00 AM and 6:00 PM |
| `0 9 1 * *` | First of month at 9:00 AM |

---

## API Reference

The web app exposes a REST API under `/api/`. Detailed schema:
[docs/API.md](API.md) and [docs/openapi.yaml](openapi.yaml).

### Authentication

```bash
# X-API-Key header (set API_KEYS env var to enable)
curl -H "X-API-Key: your-api-key" http://localhost:5000/api/campaigns

# Session-cookie (after web UI login)
curl -b cookies.txt http://localhost:5000/api/campaigns
```

### Common endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/status` | System status |
| `GET` | `/api/campaigns` | List campaigns |
| `POST` | `/api/campaigns` | Create campaign |
| `GET` | `/api/smtp` | List SMTP servers |
| `POST` | `/api/smtp` | Add SMTP server (use `tls_mode`) |
| `PUT` | `/api/smtp/<name>` | Update SMTP server |
| `POST` | `/api/smtp/test/<name>` | Test connection (by name; numeric id was removed) |
| `GET` | `/api/dead-letter` | Failed-message queue |
| `POST` | `/api/dead-letter/discard-all` | Bulk-resolve queue |
| `GET` | `/api/stats` | Aggregate stats |
| `GET` | `/health` / `/live` / `/ready` | Health checks |

### Example: create campaign

```bash
curl -X POST http://localhost:5000/api/campaigns \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-key" \
  -d '{
    "name": "API Campaign",
    "subject": "Hello {{first_name}}!",
    "from_email": "sender@example.com",
    "from_name": "MerCury",
    "recipients_path": "data/recipients.csv",
    "template_path": "templates/email.html",
    "include_default_body": true,
    "dry_run": true
  }'
```

---

## Production Deployment (systemd)

### 1. System packages

**Ubuntu/Debian:**

```bash
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3.12-dev \
    build-essential libpq-dev libffi-dev libssl-dev
```

**RHEL/Fedora:**

```bash
sudo dnf install -y python3.12 python3.12-devel \
    gcc libffi-devel openssl-devel postgresql-devel
```

### 2. App user + directory

```bash
sudo useradd -r -s /bin/false mercury
sudo mkdir -p /opt/mercury
sudo chown mercury:mercury /opt/mercury
```

### 3. Install application

```bash
sudo -u mercury git clone https://github.com/0fukuAkz/MerCury.git /opt/mercury
cd /opt/mercury
sudo -u mercury python3.12 -m venv venv
sudo -u mercury ./venv/bin/pip install --upgrade pip
sudo -u mercury ./venv/bin/pip install -e .
```

### 4. Configure `/opt/mercury/.env`

```bash
SECRET_KEY=<openssl rand -hex 32>
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<strong password>
ADMIN_EMAIL=admin@yourdomain.com
TRACKING_BASE_URL=https://mail.yourdomain.com
DATABASE_URL=postgresql://mercury:mercury@localhost/mercury
API_KEYS=key1,key2
RATE_LIMIT_STORAGE=redis://localhost:6379/0
FLASK_ENV=production
```

Lock it down: `chmod 600 /opt/mercury/.env`.

### 5. Apply migrations (out-of-band, before workers start)

```bash
sudo -u mercury ./venv/bin/alembic upgrade head
```

### 6. Systemd service

Create `/etc/systemd/system/mercury.service`:

```ini
[Unit]
Description=MerCury Email Platform
After=network.target

[Service]
Type=notify
User=mercury
Group=mercury
WorkingDirectory=/opt/mercury
EnvironmentFile=/opt/mercury/.env
# SocketIO async backend MUST agree with the gunicorn worker class.
# The mercury package defaults to 'threading' so dev/test paths work
# out of the box; this is the production opt-in. Without it,
# live-progress events queue but never reach connected browsers.
Environment=SOCKETIO_ASYNC_MODE=eventlet
# eventlet worker + single worker process is REQUIRED — the SocketIO
# and async-sender wiring assume a single process. Do not change -w.
ExecStart=/opt/mercury/venv/bin/gunicorn \
    --worker-class eventlet \
    -w 1 \
    --bind 0.0.0.0:5000 \
    --timeout 120 \
    --access-logfile /var/log/mercury/access.log \
    --error-logfile  /var/log/mercury/error.log \
    "mercury.web.app:create_app()"
ExecReload=/bin/kill -s HUP $MAINPID
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 7. Start

```bash
sudo mkdir -p /var/log/mercury
sudo chown mercury:mercury /var/log/mercury

sudo systemctl daemon-reload
sudo systemctl enable mercury
sudo systemctl start mercury
sudo systemctl status mercury
```

---

## Docker Deployment

The repo ships a production [`Dockerfile`](../Dockerfile) (multi-stage,
non-root user, stdlib `HEALTHCHECK`) and [`docker-compose.yml`](../docker-compose.yml).
The compose stack wires postgres + redis + a one-shot migration container +
the web service, and uses `${VAR:?error}` enforcement so missing secrets fail
at `docker compose up` time instead of at boot.

### Compose (recommended)

```bash
# 1. Generate a .env file (all of these are required by the compose stack)
cat > .env <<'EOF'
SECRET_KEY=<openssl rand -hex 32>
POSTGRES_PASSWORD=<strong db password>
REDIS_PASSWORD=<strong redis password>
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<strong password>
ADMIN_EMAIL=admin@yourdomain.com
TRACKING_BASE_URL=https://mail.yourdomain.com
# Optional observability:
# SENTRY_DSN=https://<key>@<org>.ingest.sentry.io/<project>
# METRICS_TOKEN=<random token to gate GET /metrics>
EOF

# 2. Bring the stack up (web is published on 127.0.0.1:5050)
docker compose up -d

# 3. Tail logs
docker compose logs -f web

# 4. (optional) once your domain points here and deploy/Caddyfile has your
#    hostname, add the TLS-terminating reverse proxy:
docker compose --profile proxy up -d
```

The compose file:

- Waits for postgres + redis to pass their healthchecks, runs the
  `migrations` service once, and waits for it to *complete*
  (`service_completed_successfully`) before `web` starts — no boot race.
- Uses Postgres for `DATABASE_URL` and Redis for `RATE_LIMIT_STORAGE` —
  the two configs the production preflight now hard-requires.
- Publishes `web` on `127.0.0.1:5050` only; front it with the optional
  `proxy` (Caddy) service for TLS, or your own reverse proxy.
- Persists the database in the `postgres_data` volume.

### Building / running by hand

```bash
docker build -t mercury .
docker run -d --name mercury \
  -p 127.0.0.1:5050:5050 \
  --env-file .env \
  -e DATABASE_URL=postgresql://user:pass@your-db:5432/mercury \
  -e RATE_LIMIT_STORAGE=redis://your-redis:6379/0 \
  mercury
```

The image runs as a non-root user; its `CMD` is (with `PORT` defaulting to 5050):

```text
gunicorn --worker-class eventlet -w 1 --bind 0.0.0.0:$PORT \
  mercury.web.app:create_app()
```

### Observability (Sentry + Prometheus)

- **Errors:** set `SENTRY_DSN` to stream exceptions to Sentry. PII is off by
  default — recipient data is never sent; opt into performance tracing with
  `SENTRY_TRACES_SAMPLE_RATE`, and tag releases with `MERCURY_RELEASE`.
- **Metrics:** `GET /metrics` exposes Prometheus counters plus process metrics.
  Single-worker means the in-process registry is complete, so no multiprocess
  setup is needed. Scrape it on the internal network, or gate it with
  `METRICS_TOKEN` (`Authorization: Bearer <token>` or `?token=`); the sample
  Caddyfile blocks `/metrics` at the public edge.
  - **HTTP (RED):** `mercury_http_requests_total{method,endpoint,status}`,
    `mercury_http_request_duration_seconds` (labelled by route template).
  - **Send pipeline:** `mercury_emails_sent_total`,
    `mercury_emails_failed_total{type}` (type ∈ transient/permanent/unknown/
    exception/other), `mercury_campaigns_active` (gauge). Good Grafana panels:
    send rate (`rate(mercury_emails_sent_total[5m])`), failure ratio, and
    active-campaign count.

Both libraries ship in the image. With `SENTRY_DSN` unset, Sentry stays dormant
and `/metrics` is still served.

---

## Scaling the web tier (multi-worker)

MerCury defaults to a single worker because its asyncio loop, SocketIO emit
bridge, and in-memory rate limiters are per-process. To run multiple web workers
(or replicas), externalize that state — set **all** of:

| Set on `web` | Why |
|---|---|
| `WEB_CONCURRENCY=<N>` (or gunicorn `-w N`) | the worker count itself |
| `SOCKETIO_MESSAGE_QUEUE=redis://...` | live progress fans out to clients on any worker |
| `RATE_LIMIT_STORAGE=redis://...` | rate limits shared across workers |
| `CAMPAIGN_EXECUTION_MODE=worker` + run the `worker` service | execution moves off the web process |

With all four in place the production preflight permits `WEB_CONCURRENCY>1`
(otherwise it warns, naming what's missing). Bring up the worker tier with
`docker compose --profile worker up -d`.

> **Status:** the machinery is wired and unit-tested, but a multi-worker
> deployment should be **validated in staging** (live event fan-out, shared
> limits, worker execution) before production — the single-worker path remains
> the proven default.

---

## SSL/TLS & Reverse Proxy

### Let's Encrypt with Certbot

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d mercury.yourdomain.com
sudo systemctl enable certbot.timer
```

### Self-signed (dev only)

```bash
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout /etc/ssl/private/mercury.key \
  -out    /etc/ssl/certs/mercury.crt \
  -subj   "/CN=mercury.local"
```

### Nginx reverse proxy

`/etc/nginx/sites-available/mercury`:

```nginx
server {
    listen 80;
    server_name mercury.yourdomain.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name mercury.yourdomain.com;

    ssl_certificate     /etc/letsencrypt/live/mercury.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/mercury.yourdomain.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 86400;
    }

    location /socket.io {
        proxy_pass http://127.0.0.1:5000/socket.io;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
}
```

Enable:

```bash
sudo ln -s /etc/nginx/sites-available/mercury /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

---

## WeasyPrint (optional)

Only needed if you generate high-quality PDF attachments. Install the
extra:

```bash
pip install -e ".[pdf]"
```

System dependencies:

| OS | Command |
|---|---|
| Ubuntu/Debian | `sudo apt install libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0 libffi-dev libcairo2 libpango1.0-dev` |
| macOS | `brew install cairo pango gdk-pixbuf libffi` |
| Windows | Install GTK3 runtime (MSYS2: `pacman -S mingw-w64-x86_64-gtk3`) |

---

## Troubleshooting

### Port already in use

```bash
lsof -i :5000                          # Linux/macOS
netstat -ano | findstr :5000           # Windows
kill -9 <PID>
```

### SQLite "database is locked"

```bash
ls -la data/*.db*
rm -f data/mercury.db-wal data/mercury.db-shm
```

### "TrackingService requires base_url"

Set `TRACKING_BASE_URL` to your public dashboard URL. The service
deliberately refuses to fall back to localhost — see
[CHANGELOG.md](../CHANGELOG.md) "Removed (BREAKING)" for the rationale.

### "ADMIN_PASSWORD is not set and FLASK_ENV=production"

Set `ADMIN_USERNAME`, `ADMIN_PASSWORD`, and `ADMIN_EMAIL` in your
environment before booting in production. There is no fallback.

### SMTP connection refused

1. Check firewall allows outbound on 25 / 465 / 587.
2. Verify SMTP credentials by running `mercury test config/campaign.yaml`
   or the `/smtp` test button in the web UI.
3. For Gmail, use an [App Password](https://support.google.com/accounts/answer/185833).

### Permission denied on `/opt/mercury`

```bash
sudo chown -R mercury:mercury /opt/mercury
chmod 755 /opt/mercury
chmod 600 /opt/mercury/.env
```

### "use_tls / use_ssl are no longer accepted"

The SMTP API and YAML loader were tightened — send `tls_mode` (one of
`'none'`, `'starttls'`, `'ssl'`) instead. See
[CHANGELOG.md](../CHANGELOG.md) for the migration note.

---

## Upgrading

```bash
sudo systemctl stop mercury

cd /opt/mercury
sudo -u mercury git pull origin main
sudo -u mercury ./venv/bin/pip install -e . --upgrade
sudo -u mercury ./venv/bin/alembic upgrade head

sudo systemctl start mercury
```

For upgrades that cross a breaking-change boundary, read the
`### Removed (BREAKING)` section of [CHANGELOG.md](../CHANGELOG.md) for
the target version *before* you upgrade — it lists every removed
default, env-var, and API field along with the migration step.

---

## Best Practices

### Email deliverability

1. **Warm up new IPs** — start with low volume, increase gradually.
2. **Configure SPF/DKIM/DMARC** DNS records for every `from_email`.
3. **Always include `{{unsubscribe_link}}`** — required by CAN-SPAM/GDPR.
4. **Avoid spam triggers** — no ALL CAPS, excessive punctuation, link-only bodies.
5. **Clean your list** — process bounces promptly; review `/dead-letter`.

### Performance

1. **Configure multiple SMTP servers** for load balancing and failover.
2. **Tune `max_per_minute` / `max_per_hour`** per server to match your
   provider's policy — exceeding them invites blacklisting.
3. **Use proxies** for distributed outbound IPs when sending at scale.
4. **Monitor bounce rate** — pause the campaign if it climbs above
   ~5%.

### Security

1. **Set every required env var** — there are no fallbacks. See
   [Environment Variables](#environment-variables).
2. **Use a strong `SECRET_KEY`** (≥ 32 random bytes); rotate it on a
   schedule.
3. **Terminate TLS at a reverse proxy** in production. The bundled
   Gunicorn config does not handle TLS itself.
4. **Rotate API keys** regularly; remove unused entries from
   `API_KEYS`.
5. **Read [SECURITY.md](SECURITY.md)** for the deployment hardening
   checklist and the private vulnerability reporting process.

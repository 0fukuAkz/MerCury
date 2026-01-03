# MerCury Installation Guide

Complete production deployment guide for MerCury email automation platform.

---

## Table of Contents

1. [System Requirements](#system-requirements)
2. [Quick Install (Development)](#quick-install-development)
3. [Production Deployment](#production-deployment)
4. [Docker Deployment](#docker-deployment)
5. [Configuration](#configuration)
6. [SSL/TLS Setup](#ssltls-setup)
7. [Reverse Proxy](#reverse-proxy)
8. [Troubleshooting](#troubleshooting)

---

## System Requirements

### Minimum Requirements

| Component | Requirement |
|-----------|-------------|
| **OS** | Windows 10+, Ubuntu 20.04+, macOS 12+ |
| **Python** | 3.10 or higher |
| **RAM** | 2 GB minimum (4 GB recommended) |
| **Disk** | 1 GB free space |
| **Network** | Outbound SMTP (ports 25, 465, 587) |

### Optional Dependencies

| Component | Purpose | Install Command |
|-----------|---------|-----------------|
| **WeasyPrint** | High-quality PDF generation | See [WeasyPrint Install](#weasyprint-optional) |
| **GTK3** | PDF rendering (Windows) | Download from [GTK website](https://github.com/nicm/gtk-3-osx) |
| **PostgreSQL** | Production database | `apt install postgresql` |
| **Redis** | Session caching (optional) | `apt install redis-server` |

---

## Quick Install (Development)

### Windows

```powershell
# 1. Clone repository
git clone https://github.com/your-org/mercury.git
cd mercury

# 2. Create virtual environment
python -m venv venv
.\venv\Scripts\activate

# 3. Install dependencies
pip install -e .

# 4. Run development server
python run.py
```

### Linux / macOS

```bash
# 1. Clone repository
git clone https://github.com/your-org/mercury.git
cd mercury

# 2. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -e .

# 4. Run development server
python run.py
```

Access the web UI at: **http://localhost:5000**  
Default credentials: `admin` / `admin`

---

## Production Deployment

### 1. Install System Dependencies

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3.11-dev \
    build-essential libpq-dev libffi-dev libssl-dev
```

**CentOS/RHEL:**
```bash
sudo dnf install -y python3.11 python3.11-devel \
    gcc libffi-devel openssl-devel postgresql-devel
```

### 2. Create Application User

```bash
sudo useradd -r -s /bin/false mercury
sudo mkdir -p /opt/mercury
sudo chown mercury:mercury /opt/mercury
```

### 3. Install Application

```bash
cd /opt/mercury
sudo -u mercury python3.11 -m venv venv
sudo -u mercury ./venv/bin/pip install --upgrade pip
sudo -u mercury ./venv/bin/pip install -e .
```

### 4. Configure Environment

Create `/opt/mercury/.env`:

```bash
# Security (REQUIRED - generate with: openssl rand -hex 32)
SECRET_KEY=your-secret-key-here
ADMIN_PASSWORD=secure-admin-password

# Database
DATABASE_URL=sqlite:///data/mercury.db
# For PostgreSQL:
# DATABASE_URL=postgresql://user:pass@localhost/mercury

# Optional API keys (comma-separated)
API_KEYS=key1,key2,key3

# Server settings
FLASK_ENV=production
HOST=0.0.0.0
PORT=5000
```

### 5. Install Production WSGI Server

```bash
./venv/bin/pip install gunicorn gevent
```

### 6. Create Systemd Service

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
Environment=PATH=/opt/mercury/venv/bin
EnvironmentFile=/opt/mercury/.env
ExecStart=/opt/mercury/venv/bin/gunicorn \
    --workers 4 \
    --worker-class gevent \
    --bind 0.0.0.0:5000 \
    --timeout 120 \
    --access-logfile /var/log/mercury/access.log \
    --error-logfile /var/log/mercury/error.log \
    "mercury.web:create_app()"
ExecReload=/bin/kill -s HUP $MAINPID
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 7. Start Service

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

### Using Docker Compose (Recommended)

Create `docker-compose.yml`:

```yaml
version: '3.8'

services:
  mercury:
    build: .
    ports:
      - "5000:5000"
    environment:
      - SECRET_KEY=${SECRET_KEY}
      - ADMIN_PASSWORD=${ADMIN_PASSWORD}
      - DATABASE_URL=sqlite:///data/mercury.db
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
      - ./config:/app/config
      - ./templates:/app/templates
    restart: unless-stopped

  # Optional: PostgreSQL
  # db:
  #   image: postgres:15
  #   environment:
  #     POSTGRES_DB: mercury
  #     POSTGRES_USER: mercury
  #     POSTGRES_PASSWORD: ${DB_PASSWORD}
  #   volumes:
  #     - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
```

Run:

```bash
# Create .env file
echo "SECRET_KEY=$(openssl rand -hex 32)" > .env
echo "ADMIN_PASSWORD=your-secure-password" >> .env

# Start containers
docker-compose up -d

# View logs
docker-compose logs -f mercury
```

### Using Docker Only

```bash
# Build image
docker build -t mercury .

# Run container
docker run -d \
    --name mercury \
    -p 5000:5000 \
    -e SECRET_KEY=$(openssl rand -hex 32) \
    -e ADMIN_PASSWORD=secure-password \
    -v $(pwd)/data:/app/data \
    -v $(pwd)/logs:/app/logs \
    mercury
```

---

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SECRET_KEY` | Flask session encryption key | Random |
| `ADMIN_PASSWORD` | Web UI admin password | `admin` |
| `DATABASE_URL` | Database connection string | `sqlite:///data/...` |
| `API_KEYS` | Comma-separated API keys | None |
| `HOST` | Server bind address | `127.0.0.1` |
| `PORT` | Server port | `5000` |
| `LOG_LEVEL` | Logging level | `INFO` |
| `SMTP_TIMEOUT` | SMTP connection timeout | `30` |

### Directory Structure

```
/opt/mercury/
├── config/
│   ├── campaign.yaml      # Campaign configuration
│   └── placeholders.yaml  # Static placeholders
├── templates/
│   └── email.html         # Email templates
├── data/
│   ├── recipients.csv     # Recipients list
│   ├── mercury.db         # SQLite database
│   └── suppression.txt    # Suppression list
├── logs/
│   ├── success.txt        # Sent emails log
│   └── failed.txt         # Failed emails log
└── .env                   # Environment variables
```

---

## SSL/TLS Setup

### Option 1: Let's Encrypt with Certbot

```bash
# Install certbot
sudo apt install certbot python3-certbot-nginx

# Get certificate
sudo certbot --nginx -d mercury.yourdomain.com

# Auto-renewal
sudo systemctl enable certbot.timer
```

### Option 2: Self-Signed Certificate

```bash
openssl req -x509 -nodes -days 365 \
    -newkey rsa:2048 \
    -keyout /etc/ssl/private/mercury.key \
    -out /etc/ssl/certs/mercury.crt \
    -subj "/CN=mercury.local"
```

---

## Reverse Proxy

### Nginx Configuration

Create `/etc/nginx/sites-available/mercury`:

```nginx
server {
    listen 80;
    server_name mercury.yourdomain.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name mercury.yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/mercury.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/mercury.yourdomain.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
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

## WeasyPrint (Optional)

For high-quality PDF generation:

### Windows
```powershell
# Install GTK3 runtime
# Download from: https://github.com/nicm/gtk-3-osx
# Or use MSYS2:
pacman -S mingw-w64-x86_64-gtk3

pip install weasyprint
```

### Ubuntu/Debian
```bash
sudo apt install libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0 \
    libffi-dev libcairo2 libpango1.0-dev
pip install weasyprint
```

### macOS
```bash
brew install cairo pango gdk-pixbuf libffi
pip install weasyprint
```

---

## Troubleshooting

### Port Already in Use

```bash
# Find process using port
lsof -i :5000
# or on Windows:
netstat -ano | findstr :5000

# Kill process
kill -9 <PID>
```

### Database Locked (SQLite)

```bash
# Check for lock files
ls -la data/*.db*

# Remove stale locks
rm -f data/mercury.db-wal data/mercury.db-shm
```

### SMTP Connection Refused

1. Check firewall allows outbound on ports 25, 465, 587
2. Verify SMTP credentials
3. For Gmail, use [App Passwords](https://support.google.com/accounts/answer/185833)

### Permission Denied

```bash
sudo chown -R mercury:mercury /opt/mercury
chmod 755 /opt/mercury
chmod 600 /opt/mercury/.env
```

---

## Upgrading

```bash
# Stop service
sudo systemctl stop mercury

# Pull latest
cd /opt/mercury
git pull origin main

# Update dependencies
./venv/bin/pip install -e . --upgrade

# Run migrations (if any)
./venv/bin/alembic upgrade head

# Restart
sudo systemctl start mercury
```

# MerCury Usage Guide

Complete guide to using MerCury for email campaign automation.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Web Dashboard](#web-dashboard)
3. [CLI Commands](#cli-commands)
4. [Campaign Configuration](#campaign-configuration)
5. [Email Templates](#email-templates)
6. [Placeholders & Variables](#placeholders--variables)
7. [Rotation & A/B Testing](#rotation--ab-testing)
8. [SMTP Configuration](#smtp-configuration)
9. [Proxy Configuration](#proxy-configuration)
10. [Tracking & Analytics](#tracking--analytics)
11. [Scheduling](#scheduling)
12. [API Reference](#api-reference)

---

## Quick Start

### 1. Start the Server

```bash
python run.py
# or
mercury start server
```

### 2. Access Web UI

Open **http://localhost:5000**

Default credentials:
- **Username:** `admin`
- **Password:** `admin`

### 3. Create Your First Campaign

1. Navigate to **Campaigns → New Campaign**
2. Fill in campaign details
3. Configure SMTP settings
4. Upload recipients or enter recipients file path
5. Click **Create Campaign**

---

## Web Dashboard

### Pages Overview

| Page | URL | Purpose |
|------|-----|---------|
| Dashboard | `/` | Overview stats, recent activity |
| Campaigns | `/campaigns` | Manage email campaigns |
| New Campaign | `/campaigns/new` | Create campaign with full options |
| SMTP Servers | `/smtp` | Configure mail servers |
| Templates | `/templates` | Email template management |
| Recipients | `/recipients` | Recipient list management |
| Scheduling | `/scheduling` | Schedule campaigns |
| Bounces | `/bounces` | View bounce notifications |
| Dead Letter | `/dead-letter` | Failed message queue |
| Webhooks | `/webhooks` | Configure event webhooks |
| Logs | `/logs` | View sending logs |
| Tools | `/tools` | Utility tools |

---

## CLI Commands

### Project Management

```bash
# Create new project with all files
mercury new project

# Create specific files
mercury new config
mercury new template
```

### Configuration

```bash
# Validate configuration
mercury check config/campaign.yaml

# Test SMTP connections
mercury test config/campaign.yaml
```

### Sending

```bash
# Preview campaign (dry run)
mercury send config/campaign.yaml --preview

# Send to first N recipients only
mercury send config/campaign.yaml --to 10

# Send full campaign
mercury send config/campaign.yaml
```

### Monitoring

```bash
# View statistics
mercury show stats

# View recent logs
mercury show logs

# Start web dashboard
mercury start server
```

---

## Campaign Configuration

### Basic Campaign YAML

```yaml
campaign:
  name: "Q1 Newsletter"
  description: "January newsletter to subscribers"

smtp_providers:
  - name: primary
    host: smtp.gmail.com
    port: 587
    username: your-email@gmail.com
    password: your-app-password
    use_tls: true
    max_per_minute: 30

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
bob@example.com,Bob,Wilson,StartupXYZ
```

---

## Email Templates

### Basic HTML Template

```html
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{{subject}}</title>
</head>
<body>
    <h1>Hello {{first_name}},</h1>
    
    <p>Welcome to our newsletter!</p>
    
    <p>
        <a href="{{link}}">Click here</a> to learn more.
    </p>
    
    <p>Best regards,<br>The MerCury Team</p>
    
    <hr>
    <small>
        <a href="{{unsubscribe_link}}">Unsubscribe</a>
    </small>
</body>
</html>
```

### Conditional Content

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

---

## Placeholders & Variables

### Recipient Data

| Placeholder | Description | Example |
|-------------|-------------|---------|
| `{{email}}` | Recipient email | john@example.com |
| `{{first_name}}` | First name | John |
| `{{last_name}}` | Last name | Doe |
| `{{company}}` | Company name | Acme Inc |
| `{{domain}}` | Email domain | example.com |

### Date & Time

| Placeholder | Description | Example |
|-------------|-------------|---------|
| `{{date}}` | Current date | 2026-01-02 |
| `{{time}}` | Current time | 14:30:00 |
| `{{day_name}}` | Day of week | Thursday |
| `{{month_name}}` | Month name | January |
| `{{year}}` | Current year | 2026 |
| `{{date_formatted}}` | Long date | January 2, 2026 |

### Random Data

| Placeholder | Description |
|-------------|-------------|
| `{{uuid}}` | Random UUID |
| `{{random_number}}` | Random number |
| `{{random_name}}` | Random name |
| `{{random_company}}` | Random company |

### Links & Tracking

| Placeholder | Description |
|-------------|-------------|
| `{{link}}` | Rotating link URL |
| `{{unsubscribe_link}}` | Unsubscribe URL |
| `{{qr_code}}` | QR code image |
| `{{tracking_pixel}}` | Open tracking pixel |

---

## Rotation & A/B Testing

### Subject Line Rotation

In the web UI, enter one subject per line:

```
🚀 Exclusive Offer Inside!
⭐ You're Invited: Special Event
📧 Important Update for {{first_name}}
```

### From Name Rotation

```
John Smith
Marketing Team
MerCury Support
```

### From Email Rotation

```
sender1@domain.com
sender2@domain.com
noreply@domain.com
```

### Template Rotation

```
templates/variant_a.html
templates/variant_b.html
templates/variant_c.html
```

### Link URL Rotation

```
https://landing1.example.com
https://landing2.example.com
https://offers.example.com
```

### Rotation Strategies

| Strategy | Description |
|----------|-------------|
| **Round Robin** | Cycles through items sequentially |
| **Random** | Random selection each time |
| **Weighted** | Prioritizes higher-weighted items |
| **Sequential** | Uses items in order |

---

## SMTP Configuration

### Single Server

```yaml
smtp_providers:
  - name: primary
    host: smtp.gmail.com
    port: 587
    username: your-email@gmail.com
    password: your-app-password
    use_tls: true
    max_per_minute: 30
    max_per_hour: 500
```

### Multiple Servers (Load Balancing)

```yaml
smtp_providers:
  - name: primary
    host: smtp1.example.com
    port: 587
    username: user1
    password: pass1
    weight: 2.0
    max_per_minute: 50

  - name: secondary
    host: smtp2.example.com
    port: 465
    username: user2
    password: pass2
    use_ssl: true
    weight: 1.0
    max_per_minute: 30

  - name: backup
    host: smtp3.example.com
    port: 587
    username: user3
    password: pass3
    weight: 0.5
    priority: -1  # Lower priority = failover
```

### Web UI Format

In the SMTP Servers textarea:
```
smtp1.example.com:587:user1:pass1
smtp2.example.com:465:user2:pass2
smtp3.example.com:587:user3:pass3
```

---

## Proxy Configuration

### Format

```
host:port
host:port:username:password
socks5://host:port
socks5://host:port:username:password
```

### Example List

```
proxy1.example.com:8080
proxy2.example.com:8080:proxyuser:proxypass
socks5://socks.example.com:1080
socks5://socks.example.com:1080:user:pass
```

### Proxy Rotation Strategies

| Strategy | Description |
|----------|-------------|
| **None** | No proxy (direct connection) |
| **Round Robin** | Rotate through proxies |
| **Random** | Random proxy each request |
| **Per Email** | Different proxy per email |

---

## Tracking & Analytics

### Enable Tracking

In campaign configuration:
- ✅ **Enable Tracking** - Master toggle
- ✅ **Track Opens** - 1x1 pixel tracking
- ✅ **Track Clicks** - Link click tracking
- **Tracking Base URL** - Custom tracking domain

### View Statistics

**Dashboard** shows:
- Total sent
- Success rate
- Open rate
- Click rate
- Bounce rate

**Logs** page shows:
- Success log
- Failed log
- Bounce notifications

---

## Scheduling

### One-Time Schedule

1. Go to **Scheduling**
2. Select campaign
3. Choose **One Time**
4. Set date and time
5. Click **Schedule**

### Recurring Schedule

1. Go to **Scheduling**
2. Select campaign
3. Choose **Recurring**
4. Enter cron expression (e.g., `0 9 * * 1` = Monday 9am)
5. Click **Schedule**

### Interval Schedule

1. Go to **Scheduling**
2. Select campaign
3. Choose **Interval**
4. Set hours/minutes between runs
5. Click **Schedule**

### Cron Expression Examples

| Expression | Description |
|------------|-------------|
| `0 9 * * *` | Daily at 9:00 AM |
| `0 9 * * 1` | Every Monday at 9:00 AM |
| `0 9,18 * * *` | Daily at 9:00 AM and 6:00 PM |
| `0 9 1 * *` | First of month at 9:00 AM |

---

## API Reference

### Authentication

```bash
# Using API key
curl -H "X-API-Key: your-api-key" http://localhost:5000/api/campaigns

# Using session (after login)
curl -b cookies.txt http://localhost:5000/api/campaigns
```

### Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/status` | System status |
| `GET` | `/api/campaigns` | List campaigns |
| `POST` | `/api/campaigns` | Create campaign |
| `GET` | `/api/smtp` | List SMTP servers |
| `POST` | `/api/smtp/test/{name}` | Test SMTP connection |
| `GET` | `/api/stats` | View statistics |
| `GET` | `/api/logs/success` | Success log |
| `GET` | `/api/logs/failed` | Failed log |
| `GET` | `/health` | Health check |

### Create Campaign (API)

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
    "dry_run": true
  }'
```

---

## Best Practices

### Email Deliverability

1. **Warm up new IPs** - Start with low volume
2. **Use SPF/DKIM/DMARC** - Configure DNS records
3. **Include unsubscribe link** - Required by law
4. **Avoid spam triggers** - No ALL CAPS, excessive punctuation
5. **Clean your list** - Remove bounces promptly

### Performance

1. **Use multiple SMTP servers** for load balancing
2. **Set appropriate rate limits** to avoid blacklisting
3. **Use proxies** for distributed sending
4. **Monitor bounce rates** and pause if too high

### Security

1. **Change default password** immediately
2. **Use environment variables** for secrets
3. **Enable HTTPS** in production
4. **Rotate API keys** regularly

# MerCury

Complete email automation. Send campaigns the easy way.

**v2.0.0** - Complete rewrite with English-like commands.

## Quick Start

```bash
# Install
pip install -e .

# Create project files
mercury new project

# Edit your config
notepad config/campaign.yaml

# Check configuration
mercury check config/campaign.yaml

# Test SMTP connection
mercury test config/campaign.yaml

# Preview (no actual sending)
mercury send config/campaign.yaml --preview

# Send for real
mercury send config/campaign.yaml
```

## Commands

| Command | Description |
|---------|-------------|
| `mercury new project` | Create config, template, and recipients files |
| `mercury new config` | Create config file only |
| `mercury new template` | Create email template |
| `mercury check <config>` | Validate your configuration |
| `mercury test <config>` | Test SMTP connections |
| `mercury send <config>` | Send your campaign |
| `mercury send <config> --preview` | Preview without sending |
| `mercury send <config> --to 10` | Send to first 10 only |
| `mercury show stats` | View sending statistics |
| `mercury show logs` | View recent log entries |
| `mercury start server` | Launch web dashboard |

## Configuration

Create `config/campaign.yaml`:

```yaml
campaign:
  name: "My Campaign"

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
  from_email: your-email@gmail.com
  from_name: "Your Name"

template:
  html: templates/email.html

recipients:
  source: data/recipients.csv

sending:
  dry_run: true
  concurrency: 50
```

## Recipients File

Create `data/recipients.csv`:

```csv
email,first_name,last_name,company
john@example.com,John,Doe,Acme Inc
jane@example.com,Jane,Smith,Tech Corp
```

## Email Template

Create `templates/email.html`:

```html
<!DOCTYPE html>
<html>
<body>
    <h1>Hello {{first_name}},</h1>
    <p>Welcome to {{company_name}}!</p>
    <p>Best regards</p>
</body>
</html>
```

## Placeholders

| Placeholder | Example |
|-------------|---------|
| `{{email}}` | john@example.com |
| `{{first_name}}` | John |
| `{{last_name}}` | Doe |
| `{{domain}}` | example.com |
| `{{date}}` | 2024-01-15 |
| `{{date_formatted}}` | January 15, 2024 |
| `{{year}}` | 2024 |
| `{{unsubscribe_link}}` | https://... |

### Conditional Content

```html
{{if:first_name}}
  <p>Hello {{first_name}},</p>
{{else}}
  <p>Hello,</p>
{{endif}}
```

## Web Dashboard

```bash
mercury start server
```

Open http://localhost:8080

- **Login:** admin / admin
- Change password via `ADMIN_PASSWORD` environment variable

## Environment Variables (Optional)

```bash
# Web UI admin password (default: admin)
export ADMIN_PASSWORD="secure-password"

# Security key for sessions
export SECRET_KEY="your-secret-key"
```

## Features

### Sending Engine
- Async sending with aiosmtplib (100-300 emails/sec)
- Connection pooling with circuit breaker
- Multi-SMTP load balancing
- Rate limiting (per minute/hour)
- Retry queue with exponential backoff

### Tracking
- Open tracking (1x1 pixel)
- Click tracking (link wrapping)
- Unsubscribe handling
- Bounce processing

### Templates
- 50+ built-in placeholders
- Conditional content
- Template includes
- A/B testing (subject/template rotation)

### Document Generation
- QR codes
- PDF attachments
- DOCX attachments
- Email as image

### Integrations
- Webhook notifications
- Scheduled sending (cron)
- Health check endpoints

## API

The web dashboard includes a REST API:

```bash
# Get status
curl http://localhost:8080/api/status

# With API key
curl -H "X-API-Key: your-key" http://localhost:8080/api/campaigns
```

Set API keys: `export API_KEYS="key1,key2,key3"`

### Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/status` | System status |
| `GET /api/campaigns` | List campaigns |
| `GET /api/smtp` | List SMTP servers |
| `POST /api/smtp/test/{name}` | Test SMTP connection |
| `GET /api/stats` | View statistics |
| `GET /health` | Health check |

## Troubleshooting

### SMTP Connection Failed

```
Error: Connection refused
```

- Check host/port are correct
- Try port 465 with `use_ssl: true`
- For Gmail, use an [App Password](https://support.google.com/accounts/answer/185833)

### Rate Limited

```
Error: 421 Too many connections
```

- Reduce `batch_size` in config
- Add more SMTP servers for load balancing

### Template Not Found

- Use path relative to project root
- Check file exists: `ls templates/`

## Project Structure

```
your-project/
├── config/
│   └── campaign.yaml      # Campaign configuration
├── templates/
│   └── email.html         # Email template
├── data/
│   ├── recipients.csv     # Recipients list
│   └── suppression_list.txt
├── logs/
│   ├── success-emails.txt
│   └── failed-emails.txt
└── .env                   # Environment variables
```

## License

MIT

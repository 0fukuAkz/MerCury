# Quick Start Guide

Get up and running in 5 minutes.

## 1. Install

```bash
pip install -e .
```

## 2. Create Project

```bash
sender new project
```

This creates:
- `config/campaign.yaml` - Configuration
- `templates/email.html` - Email template
- `data/recipients.csv` - Sample recipients

## 3. Edit Configuration

Open `config/campaign.yaml` and add your SMTP credentials:

```yaml
smtp_providers:
  - name: primary
    host: smtp.gmail.com
    port: 587
    username: your-email@gmail.com
    password: your-app-password
    use_tls: true

email:
  subject: "Hello {{first_name}}!"
  from_email: your-email@gmail.com
  from_name: "Your Name"
```

## 4. Add Recipients

Edit `data/recipients.csv`:

```csv
email,first_name,last_name
john@example.com,John,Doe
jane@example.com,Jane,Smith
```

## 5. Check Configuration

```bash
sender check config/campaign.yaml
```

## 6. Test SMTP

```bash
sender test config/campaign.yaml
```

## 7. Preview

```bash
sender send config/campaign.yaml --preview
```

## 8. Send

```bash
sender send config/campaign.yaml
```

## 9. View Stats

```bash
sender show stats
```

---

## Commands

| Command | Description |
|---------|-------------|
| `sender new project` | Create project files |
| `sender check <config>` | Validate config |
| `sender test <config>` | Test SMTP |
| `sender send <config>` | Send emails |
| `sender send <config> --preview` | Preview only |
| `sender send <config> --to 10` | First 10 only |
| `sender show stats` | View stats |
| `sender start server` | Web dashboard |

## Placeholders

| Placeholder | Example |
|-------------|---------|
| `{{email}}` | john@example.com |
| `{{first_name}}` | John |
| `{{domain}}` | example.com |
| `{{date_formatted}}` | January 15, 2024 |
| `{{unsubscribe_link}}` | Unsubscribe URL |

## Web Dashboard

```bash
sender start server
```

Open http://localhost:8080 (login: admin / admin)

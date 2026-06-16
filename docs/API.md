# Unified Sender API Reference

## Overview

The Unified Sender API provides programmatic access to the email sending platform. All API endpoints (except health checks and public endpoints) require authentication.

**Base URL:** `http://localhost:5000` (development) or your production domain

**API Version:** 2.0.0

## Authentication

### Methods

The API supports two authentication methods:

#### 1. API Key Authentication
Include your API key in the `X-API-Key` header:

```http
GET /api/campaigns HTTP/1.1
Host: api.example.com
X-API-Key: your-api-key-here
```

**Configuration:** Set the `API_KEYS` environment variable with comma-separated valid keys:

```bash
export API_KEYS="key1,key2,key3"
```

#### 2. Session Authentication
For browser-based access, authenticate via the login endpoint and use session cookies.

### Error Response

Unauthenticated requests return:

```json
{
  "error": "Authentication required"
}
```

**Status Code:** 401 Unauthorized

---

## Rate Limiting

All API endpoints are rate-limited to prevent abuse:

| Endpoint Type | Rate Limit |
|---------------|------------|
| Read operations | 30 requests/minute |
| Write operations | 10 requests/minute |
| SMTP test | 5 requests/minute |
| Default | 200/day, 50/hour |

Rate limit headers are included in responses:
- `X-RateLimit-Limit`: Maximum requests allowed
- `X-RateLimit-Remaining`: Remaining requests
- `X-RateLimit-Reset`: Unix timestamp when limit resets

---

## Endpoints

### System Status

#### GET /api/status
Get system status. **Public endpoint - no authentication required.**

**Response:**

```json
{
  "status": "ok",
  "timestamp": "2024-01-15T10:30:00Z",
  "version": "2.0.0"
}
```

---

### Campaigns

#### GET /api/campaigns
List all email campaigns.

**Rate Limit:** 30/minute

**Response:**

```json
{
  "campaigns": [
    {
      "id": 1,
      "name": "Welcome Campaign",
      "status": "completed",
      "total_recipients": 1000,
      "sent_count": 995,
      "failed_count": 5,
      "send_rate": 99.5,
      "created_at": "2024-01-15T10:00:00Z",
      "completed_at": "2024-01-15T10:30:00Z"
    }
  ]
}
```

#### POST /api/campaigns
Create a new email campaign.

**Rate Limit:** 10/minute

**Request Body:**

```json
{
  "name": "My Campaign",
  "description": "Campaign description",
  "subject": "Hello {{first_name}}!",
  "from_email": "sender@example.com",
  "from_name": "Your Company",
  "template_path": "templates/email.html",
  "recipients_path": "data/recipients.csv",
  "dry_run": true
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| name | string | ✓ | Campaign name |
| description | string | | Campaign description |
| subject | string | | Email subject line (supports placeholders) |
| from_email | string | | Sender email address |
| from_name | string | | Sender display name |
| template_path | string | | Path to HTML template |
| recipients_path | string | | Path to recipients file |
| dry_run | boolean | | If true, don't actually send emails |

**Response (201 Created):**

```json
{
  "success": true,
  "campaign": {
    "id": 1,
    "name": "My Campaign",
    "status": "draft",
    "created_at": "2024-01-15T10:00:00Z"
  }
}
```

**Error Response (400 Bad Request):**

```json
{
  "error": "Campaign name required"
}
```

#### GET /api/campaigns/{id}
Get a single campaign by ID.

#### PUT /api/campaigns/{id}
Update a campaign. Accepts the same fields as `POST /api/campaigns`.

#### DELETE /api/campaigns/{id}
Delete a campaign.

#### POST /api/campaigns/bulk-delete
Delete multiple campaigns by ID.

**Request Body:**

```json
{ "ids": [1, 2, 3] }
```

#### POST /api/campaigns/{id}/clone
Clone an existing campaign.

#### POST /api/campaigns/{id}/start
Start sending a campaign.

#### GET /api/campaigns/{id}/stats/engagement
Engagement metrics (opens, clicks, unsubscribes) for a campaign.

#### GET /api/campaigns/{id}/stats/smtp
Per-SMTP-server send stats for a campaign.

#### GET /api/campaigns/{id}/stats/geo
Geolocation breakdown of opens for a campaign.

#### GET /api/campaigns/{id}/stats/timeline
Time-series open/click activity for a campaign.

---

### SMTP Servers

#### GET /api/smtp
List all configured SMTP servers.

**Rate Limit:** 30/minute

**Response:**

```json
{
  "servers": [
    {
      "id": 1,
      "name": "primary",
      "host": "smtp.gmail.com",
      "port": 587,
      "tls_mode": "starttls",
      "is_enabled": true,
      "max_per_minute": 30,
      "max_per_hour": 500,
      "has_password": true,
      "current_minute_count": 0,
      "avg_handshake_latency": null,
      "avg_send_latency": null
    }
  ]
}
```

> **Note:** Passwords are never returned in API responses.

#### POST /api/smtp
Add a new SMTP server.

**Rate Limit:** 10/minute

**Request Body:**

```json
{
  "name": "secondary",
  "host": "smtp.sendgrid.net",
  "port": 587,
  "username": "apikey",
  "password": "SG.xxxxx",
  "tls_mode": "starttls"
}
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| host | string | ✓ | | SMTP server hostname |
| name | string | | host | Display name for the server |
| port | integer | | 587 | SMTP port |
| username | string | | | SMTP username |
| password | string | | | SMTP password |
| tls_mode | string | | `"starttls"` | TLS mode: `"none"`, `"starttls"`, or `"ssl"`. The legacy `use_tls`/`use_ssl` booleans are rejected with a 400 error. |

**Response (201 Created):**

```json
{
  "success": true,
  "server": {
    "id": 2,
    "name": "secondary",
    "host": "smtp.sendgrid.net",
    "port": 587
  }
}
```

#### PUT /api/smtp/{name}
Update an existing SMTP server. Accepts the same fields as `POST /api/smtp` (all optional).

#### DELETE /api/smtp/{name}
Remove an SMTP server.

#### POST /api/smtp/test/{name}
Test connection to a specific SMTP server.

**Rate Limit:** 5/minute

**Path Parameters:**
- `name` (string): Name of the SMTP server to test

**Response (Success):**

```json
{
  "success": true,
  "server": "primary",
  "host": "smtp.gmail.com",
  "port": 587,
  "message": "Connection successful"
}
```

**Response (Failure):**

```json
{
  "success": false,
  "server": "primary",
  "host": "smtp.gmail.com",
  "port": 587,
  "error": "Authentication failed"
}
```

#### GET /api/smtp/health
Latest health-check status for all SMTP servers. Returns `name`, `host`, `port`, `status`, `is_enabled`, `last_checked_at`, `health_error`, `health_error_type` per server.

#### POST /api/smtp/health/check
Manually trigger health checks on all enabled SMTP servers. **Rate Limit:** 5/minute.

---

### Templates

#### GET /api/templates
List all email templates.

**Rate Limit:** 30/minute

**Response:**

```json
{
  "templates": [
    {
      "id": 1,
      "name": "Welcome Email",
      "subject": "Welcome to {{company_name}}!",
      "is_active": true,
      "created_at": "2024-01-15T10:00:00Z"
    }
  ]
}
```

#### POST /api/templates/preview
Preview a template with sample data.

**Rate Limit:** 20/minute

**Request Body:**

```json
{
  "html": "<h1>Hello {{first_name}}!</h1>",
  "recipient": "test@example.com",
  "placeholders": {
    "first_name": "John",
    "company_name": "Acme Inc"
  }
}
```

**Response:**

```json
{
  "html": "<h1>Hello John!</h1>",
  "placeholders": ["first_name", "company_name"]
}
```

---

### Logs

#### GET /api/logs/success
Get up to 100 recent successful email sends.

**Rate Limit:** 30/minute

**Response:**

```json
{
  "emails": [
    {
      "email": "user@example.com",
      "time": "2024-01-15T10:00:00",
      "opens": 2,
      "clicks": 1,
      "status": "opened"
    }
  ]
}
```

#### GET /api/logs/failed
Get up to 100 recent failed email sends.

**Rate Limit:** 30/minute

**Response:**

```json
{
  "failures": [
    {
      "email": "bad@example.com",
      "error": "Mailbox not found",
      "time": "2024-01-15T10:00:00",
      "status": "failed"
    }
  ]
}
```

---

### Statistics

#### GET /api/stats
Get overall sending statistics.

**Rate Limit:** 30/minute

**Response:**

```json
{
  "total_sent": 9500,
  "total_failed": 500,
  "total_attempts": 10000,
  "success_rate": 95.0
}
```

---

### Webhooks

#### GET /api/webhooks
List registered webhooks.

**Rate Limit:** 30/minute

**Response:**

```json
{
  "webhooks": [
    {
      "id": "wh_abc123",
      "url": "https://example.com/webhook",
      "events": ["email.sent", "email.failed", "email.bounced"],
      "is_active": true
    }
  ]
}
```

#### POST /api/webhooks
Register a new webhook.

**Rate Limit:** 10/minute

**Request Body:**

```json
{
  "url": "https://example.com/webhook",
  "events": ["email.sent", "email.failed"],
  "secret": "optional-shared-secret"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| url | string | ✓ | Webhook endpoint URL |
| events | array | | Events to subscribe to |
| secret | string | | Shared secret for signature verification |

**Available Events:**
- `email.sent` - Email successfully sent
- `email.failed` - Email failed to send
- `email.bounced` - Email bounced
- `email.opened` - Email opened (tracking)
- `email.clicked` - Link clicked (tracking)
- `email.unsubscribed` - User unsubscribed

**Response (201 Created):**

```json
{
  "success": true,
  "webhook": {
    "id": "wh_def456",
    "url": "https://example.com/webhook",
    "events": ["email.sent", "email.failed"]
  }
}
```

#### DELETE /api/webhooks/{webhook_id}
Remove a webhook.

---

### Dead Letter Queue

#### GET /api/dead-letter
List unresolved dead-letter items (failed messages).

**Rate Limit:** 30/minute

#### POST /api/dead-letter/{id}/retry
Retry a dead-letter item using the internal retry queue.

#### POST /api/dead-letter/{id}/requeue
Requeue a dead-letter item by re-sending it immediately.

#### POST /api/dead-letter/requeue-all
Requeue all eligible unresolved dead-letter items.

#### DELETE /api/dead-letter/{id}
Discard (mark resolved) a dead-letter item.

#### POST /api/dead-letter/discard-all
Discard all unresolved dead-letter items.

#### GET /api/dead-letter/stats
Aggregate stats for the dead-letter queue (counts by error type, resolution rate).

---

### Recipients

#### GET /api/recipients
List available recipient CSV files.

#### POST /api/recipients/upload
Upload a recipients CSV file. `multipart/form-data` with a `file` field.

#### GET /api/recipients/{filename}/preview
Preview the first rows and column names of a recipient file.

#### DELETE /api/recipients/{filename}
Delete a recipient file.

---

### Scheduling

#### GET /api/scheduling/jobs
List all scheduled campaign jobs.

#### POST /api/scheduling/jobs
Create a new scheduled job.

**Request Body:**

```json
{
  "campaign_id": 1,
  "trigger": "cron",
  "cron_expression": "0 9 * * 1"
}
```

| Field | Type | Description |
|-------|------|-------------|
| campaign_id | integer | Campaign to schedule |
| trigger | string | `"cron"`, `"interval"`, or `"date"` |
| cron_expression | string | Standard cron expression (for `"cron"` trigger) |
| interval_hours | number | Interval in hours (for `"interval"` trigger) |
| run_date | string | ISO datetime (for `"date"` trigger) |

#### DELETE /api/scheduling/jobs/{job_id}
Remove a scheduled job.

#### POST /api/scheduling/jobs/{job_id}/pause
Pause a scheduled job.

#### POST /api/scheduling/jobs/{job_id}/resume
Resume a paused scheduled job.

---

### Bounces

#### GET /api/bounces
List recorded bounce notifications.

#### GET /api/bounces/stats
Aggregate bounce statistics by type.

---

## Health Endpoints

### GET /health
Basic health check. **Public endpoint.**

**Response:**

```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

### GET /health/detailed
Detailed health check with component status.

**Requires:** Authentication

**Response:**

```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:00Z",
  "components": {
    "database": {
      "status": "healthy",
      "type": "sqlite"
    },
    "smtp": {
      "status": "healthy",
      "active_servers": 2
    },
    "disk": {
      "status": "healthy",
      "free_gb": 45.5
    }
  }
}
```

### GET /ready
Kubernetes readiness probe. **Public endpoint.**

Returns 200 if application is ready to handle traffic, 503 otherwise.

### GET /live
Kubernetes liveness probe. **Public endpoint.**

Returns 200 if application process is alive.

---

## Tracking Endpoints

### GET /track/open/{email_id}
Tracking pixel endpoint for open detection.

Returns a 1x1 transparent GIF image.

### GET /track/click/{email_id}
Link click tracking with redirect.

**Query Parameters:**
- `url` (string): Destination URL
- `lid` (string): Optional link identifier

Redirects to the destination URL after recording the click.

### GET /track/unsubscribe/{email_id}
Process unsubscribe request.

**Query Parameters:**
- `token` (string): Secure HMAC-signed unsubscribe token

Returns unsubscribe confirmation page.

---

## Error Codes

| Status Code | Description |
|-------------|-------------|
| 200 | Success |
| 201 | Created |
| 400 | Bad Request - Invalid input |
| 401 | Unauthorized - Authentication required |
| 403 | Forbidden - Insufficient permissions |
| 404 | Not Found |
| 429 | Too Many Requests - Rate limit exceeded |
| 500 | Internal Server Error |
| 503 | Service Unavailable |

---

## Placeholder Reference

The following placeholders are available in email templates and subjects:

### Recipient Placeholders
| Placeholder | Description |
|-------------|-------------|
| `{{email}}` | Recipient email address |
| `{{first_name}}` | First name |
| `{{last_name}}` | Last name |
| `{{full_name}}` | Full name |
| `{{company}}` | Company name |
| `{{domain}}` | Email domain |

### Date/Time Placeholders
| Placeholder | Description |
|-------------|-------------|
| `{{date}}` | Current date (YYYY-MM-DD) |
| `{{date_formatted}}` | Formatted date (January 15, 2024) |
| `{{time}}` | Current time (HH:MM:SS) |
| `{{year}}` | Current year |
| `{{month_name}}` | Month name |
| `{{day_name}}` | Day name |

### Unique Identifiers
| Placeholder | Description |
|-------------|-------------|
| `{{uuid}}` | Unique identifier |
| `{{short_id}}` | 8-character short ID |
| `{{tracking_id}}` | Tracking identifier |

### Random Data (Faker)
| Placeholder | Description |
|-------------|-------------|
| `{{random_name}}` | Random full name |
| `{{random_company}}` | Random company name |
| `{{random_phone}}` | Random phone number |

### Special Placeholders
| Placeholder | Description |
|-------------|-------------|
| `{{unsubscribe_link}}` | Unsubscribe URL |
| `{{qr_code}}` | QR code image tag |
| `{{link}}` | Campaign link |

---

## OpenAPI Specification

A static OpenAPI 3.0 spec is available at [`docs/openapi.yaml`](openapi.yaml).
There is no live Swagger UI or `/api/openapi.json` route served by the application.

---

## SDK Examples

### Python

```python
import requests

API_KEY = "your-api-key"
BASE_URL = "http://localhost:5000"

headers = {"X-API-Key": API_KEY}

# List campaigns
response = requests.get(f"{BASE_URL}/api/campaigns", headers=headers)
campaigns = response.json()["campaigns"]

# Create campaign
campaign_data = {
    "name": "My Campaign",
    "subject": "Hello {{first_name}}!",
    "from_email": "sender@example.com"
}
response = requests.post(
    f"{BASE_URL}/api/campaigns",
    json=campaign_data,
    headers=headers
)
```

### cURL

```bash
# List campaigns
curl -H "X-API-Key: your-api-key" http://localhost:5000/api/campaigns

# Create campaign
curl -X POST http://localhost:5000/api/campaigns \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"name": "My Campaign", "subject": "Hello!"}'

# Test SMTP connection
curl -X POST http://localhost:5000/api/smtp/test/primary \
  -H "X-API-Key: your-api-key"
```

---

## Changelog

### Version 2.0.0
- Added API key authentication
- Implemented rate limiting
- Added webhook support
- Improved error responses
- Added health check endpoints
- OpenAPI documentation

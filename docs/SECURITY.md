# Security Policy

## Reporting a vulnerability

Please **do not** open public GitHub issues for security problems. Report
suspected vulnerabilities privately:

- **Email:** onlyh3x@protonmail.com (PGP welcome; key on request)
- **GitHub:** use [Private Vulnerability Reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
  from the "Security" tab if enabled.

Please include:

1. A description of the issue and its impact.
2. Steps to reproduce, ideally with a minimal payload or test case.
3. Affected commit / version / deployment configuration.
4. Whether the issue is already public anywhere.

### Response expectations

- **Acknowledgement:** within 5 business days.
- **Triage / severity assessment:** within 10 business days.
- **Fix or mitigation plan:** depends on severity.
  - Critical (RCE, auth bypass, data exfiltration): aim for patch within 14 days.
  - High (privilege escalation, persisted XSS, SQL injection): aim for 30 days.
  - Medium/Low: rolled into the next regular release.

We will credit reporters in the CHANGELOG unless you ask to remain anonymous.

## Supported versions

Security fixes land on `main` and ship in the latest `2.1.x` release. Older
tagged releases and pre-tag commits should upgrade to the latest.

| Version          | Supported |
|------------------|-----------|
| `main` (latest)  | ✅        |
| `2.1.x` (latest) | ✅        |
| `< 2.1`          | ❌        |

## Scope

In scope:

- The `mercury` CLI (`src/mercury/cli/`).
- The Flask + Flask-SocketIO web dashboard (`src/mercury/web/`).
- The async SMTP send pipeline (`src/mercury/engine/`).
- Authentication and session handling (`src/mercury/security/auth.py`).
- Template rendering (`src/mercury/features/template_engine.py`,
  `placeholders.py`) — particularly the `{{var}}` / `{{if:x}}…{{endif}}`
  mini-language and any path where user-controlled input can reach it.
- Webhook delivery and signature handling.
- Unsubscribe-link HMAC signing.
- Database access paths (SQL injection, mass-assignment, IDOR).
- Migration shims, including the boot-time `ALTER TABLE` in
  `src/mercury/web/app.py`.

Out of scope:

- Issues that require a pre-compromised host or root access to reproduce.
- Denial-of-service against the dev Flask server (`make dev` /
  `python -m mercury.web.app`); only the Gunicorn production runner
  (`python run.py`) is in scope.
- Default-credential findings on a deployment that ignored the
  `ADMIN_PASSWORD` / `SECRET_KEY` boot-time hard-fail. Those hard-fails are
  gated by `FLASK_ENV` (they fire in production and any non-dev environment);
  only bypasses of that gate count.
- Self-XSS or social-engineering against an authenticated administrator
  who already has full app privileges.
- Findings from automated scanners with no demonstrated impact.

## Deployment hardening checklist

Operators should ensure, before exposing the web app:

- [ ] `SECRET_KEY` set to a strong random value (≥32 bytes, e.g.
      `python -c "import secrets; print(secrets.token_hex(32))"`).
- [ ] `ADMIN_PASSWORD` set to a strong password before first boot.
      (Required: the app refuses to start in production without it.)
- [ ] `FLASK_ENV=production`.
- [ ] `data/.encryption.salt` is the per-install file MerCury generated — not a
      shared or committed value, and not checked into version control.
- [ ] `API_KEYS` set if programmatic `/api/*` access is needed.
- [ ] `UNSUBSCRIBE_SECRET` set separately from `SECRET_KEY` if you rotate
      session keys independently of unsubscribe-link signing.
- [ ] `RATE_LIMIT_STORAGE` pointing at a Redis URL (in-memory limits
      reset on restart and are not shared across workers).
- [ ] App is behind a TLS-terminating reverse proxy. `SESSION_COOKIE_SECURE`
      defaults to `True` in production; do not override unless you know why.
- [ ] Database file (SQLite) is on a non-world-readable path, or you are
      using a managed PostgreSQL instance with TLS.
- [ ] Migrations have been run (`mercury db migrate`, or `alembic upgrade head`
      from a source checkout) rather than relying on the boot-time auto-upgrade.

## Known security-relevant defaults

- **No default admin credentials.** The app refuses to create a first
  admin unless `ADMIN_USERNAME`, `ADMIN_PASSWORD`, and `ADMIN_EMAIL` are
  all set. There is no `admin / admin` fallback.
- **`SECRET_KEY` has no production default.** Without it, the app
  raises at boot in any environment where `FLASK_ENV` is not in the
  dev set (`development` / `dev` / `test` / `testing` / `local`). The
  former `MERCURY_DEV` escape hatch has been removed.
- API-key auth is disabled by default — set `API_KEYS` to enable.

## Cryptography

- Password hashing: `bcrypt` via `passlib`.
- Stored SMTP credentials: encrypted at rest (via the `cryptography` library)
  with a key derived from a passphrase and a **per-install salt** that MerCury
  generates at `<data-dir>/.encryption.salt`. The salt is unique per install
  and must not be committed — a shared salt weakens key derivation across
  deployments.
- HMAC for unsubscribe tokens: SHA-256 over `UNSUBSCRIBE_SECRET` (or
  `SECRET_KEY` fallback). Rotating either invalidates all outstanding
  unsubscribe links.
- Session cookies: signed by Flask using `SECRET_KEY`.

If you find a primitive being used incorrectly (e.g., MD5/SHA-1 in any
auth-adjacent path, raw `==` comparison on secrets, weak random sources
for tokens), please report it — those are always in scope.

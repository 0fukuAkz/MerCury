"""MerCury Email Platform CLI - Simple, English-like commands."""

import asyncio
import os
import sys
import logging

import click
from tqdm import tqdm

from ..utils.logging_config import configure_logging
from ..utils.app_dirs import get_log_dir

logger = logging.getLogger(__name__)


def banner():
    """Print banner."""
    click.echo(
        click.style(
            """
+====================================================================+
|            MerCury Email Platform - Production Platform              |
+====================================================================+
""",
            fg="cyan",
        )
    )


@click.group()
@click.version_option(version="2.1.0", prog_name="mercury")
@click.option("-v", "--verbose", is_flag=True, help="Detailed output")
@click.option("-q", "--quiet", is_flag=True, help="Minimal output")
@click.pass_context
def cli(ctx, verbose, quiet):
    """
    Send emails the easy way.

    \b
    QUICK START:
      mercury new project           Create config files
      mercury check config.yaml     Validate setup
      mercury test config.yaml      Test SMTP
      mercury send config.yaml      Send emails

    \b
    MORE COMMANDS:
      mercury show stats            View statistics
      mercury start server          Web dashboard
    """
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    ctx.obj["quiet"] = quiet

    level = "WARNING" if quiet else ("DEBUG" if verbose else "INFO")
    log_file = get_log_dir() / "mercury.log"
    configure_logging(level=level, log_file=str(log_file))


# =============================================================================
# NEW - Create things
# =============================================================================


@cli.command("new")
@click.argument("what", type=click.Choice(["project", "config", "template"]))
@click.option("-n", "--name", default=None, help="Name for the item")
@click.option("-f", "--force", is_flag=True, help="Overwrite existing")
def new(what, name, force):
    """
    Create new project files.

    \b
    EXAMPLES:
      sender new project
      sender new config
      sender new template --name welcome
    """
    banner()

    if what == "project":
        _new_project(force)
    elif what == "config":
        _new_config(name or "campaign", force)
    elif what == "template":
        _new_template(name or "email", force)


def _new_project(force):
    """Create full project."""
    for d in ["config", "templates", "data", "logs"]:
        os.makedirs(d, exist_ok=True)

    _new_config("campaign", force)
    _new_template("email", force)
    _new_recipients(force)

    click.echo(click.style("\nDone!", fg="green"))
    click.echo(
        """
Next steps:
  1. Edit config/campaign.yaml
  2. Add recipients to data/recipients.csv
  3. Run: mercury check config/campaign.yaml
  4. Run: mercury send config/campaign.yaml --preview
"""
    )


def _new_config(name, force):
    """Create config file."""
    path = f"config/{name}.yaml"
    if os.path.exists(path) and not force:
        click.echo(f"  {path} exists (use --force)")
        return

    os.makedirs("config", exist_ok=True)
    with open(path, "w") as f:
        f.write(
            """# Email Campaign Configuration

campaign:
  name: "My Campaign"

smtp_providers:
  - name: primary
    host: smtp.gmail.com
    port: 587
    username: your-email@gmail.com
    password: your-app-password
    tls_mode: starttls
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
"""
        )
    click.echo(f"  Created {path}")


def _new_template(name, force):
    """Create template file."""
    path = f"templates/{name}.html"
    if os.path.exists(path) and not force:
        click.echo(f"  {path} exists (use --force)")
        return

    os.makedirs("templates", exist_ok=True)
    with open(path, "w") as f:
        f.write(
            """<!DOCTYPE html>
<html>
<body style="font-family: Arial; max-width: 600px; margin: 0 auto;">
    <h1>Hello {{first_name}},</h1>
    <p>This is a sample email.</p>
    <p>Date: {{date_formatted}}</p>
    <hr>
    <p style="font-size: 12px; color: #666;">
        <a href="{{unsubscribe_link}}">Unsubscribe</a>
    </p>
</body>
</html>
"""
        )
    click.echo(f"  Created {path}")


def _new_recipients(force):
    """Create recipients file."""
    path = "data/recipients.csv"
    if os.path.exists(path) and not force:
        click.echo(f"  {path} exists (use --force)")
        return

    os.makedirs("data", exist_ok=True)
    with open(path, "w") as f:
        f.write(
            """email,first_name,last_name,company
john@example.com,John,Doe,Acme Inc
jane@example.com,Jane,Smith,Tech Corp
"""
        )
    click.echo(f"  Created {path}")


# =============================================================================
# CHECK - Validate configuration
# =============================================================================


@cli.command("check")
@click.argument("config_file", type=click.Path(exists=True))
def check(config_file):
    """
    Check if configuration is valid.

    \b
    EXAMPLE:
      mercury check config/campaign.yaml
    """
    from ..services.campaign_service import load_campaign_from_yaml

    click.echo(f"\nChecking {config_file}...\n")
    errors = []

    try:
        config = load_campaign_from_yaml(config_file)
        click.echo(click.style("  [OK] ", fg="green") + "Valid YAML")

        if config.name:
            click.echo(click.style("  [OK] ", fg="green") + f"Campaign: {config.name}")

        if config.from_email:
            click.echo(click.style("  [OK] ", fg="green") + f"From: {config.from_email}")
        else:
            errors.append("Missing from_email")

        if config.subject:
            click.echo(click.style("  [OK] ", fg="green") + f"Subject: {config.subject}")
        else:
            errors.append("Missing subject")

        if config.template_path and os.path.exists(config.template_path):
            click.echo(click.style("  [OK] ", fg="green") + f"Template: {config.template_path}")
        elif config.template_path:
            errors.append(f"Template not found: {config.template_path}")

        if config.recipients_path and os.path.exists(config.recipients_path):
            with open(config.recipients_path) as f:
                count = sum(1 for _ in f) - 1
            click.echo(click.style("  [OK] ", fg="green") + f"Recipients: {count}")
        elif config.recipients_path:
            errors.append(f"Recipients not found: {config.recipients_path}")

        if config.smtp_configs:
            click.echo(
                click.style("  [OK] ", fg="green") + f"SMTP: {len(config.smtp_configs)} server(s)"
            )
        else:
            errors.append("No SMTP servers")

    except Exception as e:
        errors.append(str(e))

    click.echo("")
    if errors:
        for err in errors:
            click.echo(click.style("  [X] ", fg="red") + err)
        sys.exit(1)
    else:
        click.echo(click.style("All good!", fg="green"))


# =============================================================================
# TEST - Test SMTP connections
# =============================================================================


@cli.command("test")
@click.argument("config_file", type=click.Path(exists=True))
@click.option("-s", "--server", default=None, help="Test specific server")
def test(config_file, server):
    """
    Test SMTP connections.

    \b
    EXAMPLES:
      mercury test config/campaign.yaml
      mercury test config.yaml --server primary
    """
    from ..services.campaign_service import load_campaign_from_yaml
    from ..services.smtp_service import SMTPService

    click.echo("\nTesting SMTP...\n")

    config = load_campaign_from_yaml(config_file)

    if not config.smtp_configs:
        click.echo(click.style("No SMTP servers in config", fg="red"))
        sys.exit(1)

    smtp = SMTPService()
    smtp.load_from_config(config.smtp_configs)

    async def run():
        results = await smtp.test_all_connections()
        ok = True
        for r in results:
            if server and r["server"] != server:
                continue
            if r["success"]:
                click.echo(click.style("  [OK] ", fg="green") + r["server"])
            else:
                click.echo(click.style("  [X]  ", fg="red") + f"{r['server']}: {r['error']}")
                ok = False
        return ok

    if asyncio.run(run()):
        click.echo(click.style("\nAll connections OK!", fg="green"))
    else:
        click.echo(click.style("\nSome connections failed", fg="red"))
        sys.exit(1)


# =============================================================================
# SEND - Send emails
# =============================================================================


@cli.command("send")
@click.argument("config_file", type=click.Path(exists=True))
@click.option("--preview", is_flag=True, help="Preview only, no sending")
@click.option("--to", "limit", type=int, help="Limit recipients")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
@click.pass_context
def send(ctx, config_file, preview, limit, yes):
    """
    Send email campaign.

    \b
    EXAMPLES:
      mercury send config.yaml --preview
      mercury send config.yaml --to 10
      mercury send config.yaml --yes
    """
    from ..services.campaign_service import CampaignService, load_campaign_from_yaml

    if not ctx.obj.get("quiet"):
        banner()

    config = load_campaign_from_yaml(config_file)
    if preview:
        config.dry_run = True

    service = CampaignService()
    service.initialize()
    service.load_config(config)

    # Load recipients
    if not config.recipients_path:
        click.echo(click.style("No recipients file", fg="red"))
        sys.exit(1)

    if config.recipients_path.endswith(".csv"):
        recipients = list(
            service.load_recipients_from_csv(
                config.recipients_path, email_column=config.email_column
            )
        )
    else:
        recipients = list(service.load_recipients_from_text(config.recipients_path))

    if limit:
        recipients = recipients[:limit]

    # Summary
    click.echo(f"Campaign: {config.name}")
    click.echo(f"From: {config.from_name} <{config.from_email}>")
    click.echo(f"Subject: {config.subject}")
    click.echo(f"Recipients: {len(recipients)}")

    if preview:
        click.echo(click.style("\n[PREVIEW] No emails will be sent\n", fg="yellow"))
    elif not yes:
        if not click.confirm(f"\nSend to {len(recipients)} recipients?"):
            click.echo("Cancelled.")
            return

    click.echo("")
    pbar = tqdm(total=len(recipients), desc="Sending", unit="email")

    async def progress(data):
        pbar.update(1)

    async def run():
        try:
            return await service.run_campaign(recipients, progress, "logs")
        finally:
            await service.close()

    stats = asyncio.run(run())
    pbar.close()

    click.echo(f"\nSent: {stats['sent']}")
    click.echo(f"Failed: {stats['failed']}")

    if stats["failed"] == 0:
        click.echo(click.style("Success!", fg="green"))
    else:
        click.echo(click.style("Check logs/failed-emails.txt", fg="yellow"))


# =============================================================================
# SHOW - View things
# =============================================================================


@cli.command("show")
@click.argument("what", type=click.Choice(["stats", "logs", "failed", "config"]))
@click.option("-f", "--file", default=None, help="Specific file")
def show(what, file):
    """
    Show stats, logs, or config.

    \b
    EXAMPLES:
      mercury show stats
      mercury show logs
      mercury show failed
      mercury show config
    """
    if what == "stats":
        _show_stats()
    elif what in ("logs", "failed"):
        _show_logs(file or "logs/failed-emails.txt")
    elif what == "config":
        _show_file(file or "config/campaign.yaml")


def _show_stats():
    """Show statistics."""
    success = failed = 0

    if os.path.exists("logs/success-emails.txt"):
        with open("logs/success-emails.txt") as f:
            success = sum(1 for line in f if line.strip())

    if os.path.exists("logs/failed-emails.txt"):
        with open("logs/failed-emails.txt") as f:
            failed = sum(1 for line in f if line.strip())

    total = success + failed
    rate = round(success / total * 100, 1) if total else 0

    click.echo(
        f"""
Statistics
==========
Sent:     {success}
Failed:   {failed}
Total:    {total}
Rate:     {rate}%
"""
    )


def _show_logs(path):
    """Show log file."""
    if not os.path.exists(path):
        click.echo(f"No file: {path}")
        return

    click.echo(f"\n{path}:\n")
    with open(path) as f:
        for line in f.readlines()[-20:]:
            click.echo(f"  {line.rstrip()}")


def _show_file(path):
    """Show file contents."""
    if not os.path.exists(path):
        click.echo(f"No file: {path}")
        return

    with open(path) as f:
        click.echo(f.read())


# =============================================================================
# GENERATE - Generate content (QR, PDF, Image)
# =============================================================================


@cli.group("generate")
def generate():
    """
    Generate content (QR, PDF, Image).

    \b
    EXAMPLES:
      mercury generate qr "https://example.com"
      mercury generate pdf input.html output.pdf
      mercury generate image input.html output.png
    """
    pass


@generate.command("qr")
@click.argument("data")
@click.argument("output", default="qrcode.png")
@click.option("--size", default=10, help="Box size")
def generate_qr(data, output, size):
    """Generate QR code."""
    from ..features.generators import QRCodeGenerator, GeneratorConfig

    config = GeneratorConfig(qr_box_size=size)
    gen = QRCodeGenerator(config)

    click.echo(f"Generating QR code for: {data}")
    gen.generate_to_file(data, output)
    click.echo(click.style(f"Saved to {output}", fg="green"))


@generate.command("pdf")
@click.argument("input_file", type=click.Path(exists=True))
@click.argument("output_file", default="output.pdf")
def generate_pdf(input_file, output_file):
    """Convert HTML to PDF."""
    from ..features.generators import PDFGenerator, GeneratorConfig

    with open(input_file, "r", encoding="utf-8") as f:
        content = f.read()

    click.echo(f"Converting {input_file} to PDF...")
    gen = PDFGenerator(GeneratorConfig())
    gen.generate_from_html(content, output_file)
    click.echo(click.style(f"Saved to {output_file}", fg="green"))


@generate.command("image")
@click.argument("input_file", type=click.Path(exists=True))
@click.argument("output_file", default="output.png")
def generate_image(input_file, output_file):
    """Convert HTML to Image."""
    from ..features.generators import ImageGenerator, GeneratorConfig

    with open(input_file, "r", encoding="utf-8") as f:
        content = f.read()

    click.echo(f"Converting {input_file} to Image...")
    gen = ImageGenerator(GeneratorConfig())
    gen.generate_from_html(content, output_file)
    click.echo(click.style(f"Saved to {output_file}", fg="green"))


# =============================================================================
# START - Start server
# =============================================================================


@cli.command("start")
@click.argument("what", type=click.Choice(["server", "web", "dashboard"]), default="server")
@click.option(
    "-p", "--port", default=5000, help="Port number (default: 5000, matches `python run.py`)"
)
@click.option("--open", "open_browser", is_flag=True, help="Open browser")
@click.option("--debug", is_flag=True, default=False, help="Enable debug mode")
def start(what, port, open_browser, debug):
    """
    Start web dashboard (Flask/SocketIO dev runner).

    For production, prefer `python run.py` — it execs gunicorn + eventlet
    with a single worker, which is what the async sender thread and SocketIO
    wiring assume. This `start` command runs Flask directly and is intended
    for CLI-driven local iteration.

    \b
    EXAMPLES:
      mercury start server
      mercury start server --port 3000
      mercury start --open
      mercury start --debug
    """
    banner()

    from ..web.app import create_app, socketio

    click.echo(f"Dashboard: http://127.0.0.1:{port}")
    click.echo("Login: use your configured ADMIN_USERNAME / ADMIN_PASSWORD")
    click.echo("Press Ctrl+C to stop\n")

    if open_browser:
        import webbrowser

        webbrowser.open(f"http://127.0.0.1:{port}")

    app = create_app(config={"DEBUG": debug})

    if socketio:
        socketio.run(app, host="127.0.0.1", port=port, debug=debug)
    else:
        app.run(host="127.0.0.1", port=port, debug=debug)


# =============================================================================
# Database management
# =============================================================================


@cli.group("db")
def db():
    """Database / migration management."""


@db.command("migrate")
@click.option(
    "--revision",
    default="head",
    help="Target revision (default: head). Use a revision id to upgrade/downgrade to a specific point.",
)
def db_migrate(revision: str):
    """Apply Alembic migrations to the database.

    Run this once before starting the web app in production. The web app only
    runs migrations on boot in non-production environments (`FLASK_ENV` !=
    `production`) to avoid multi-worker boot races.
    """
    import os
    from alembic.config import Config as AlembicConfig
    from alembic import command as alembic_command

    alembic_ini = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "alembic.ini")
    )
    if not os.path.isfile(alembic_ini):
        click.echo(f"Error: alembic.ini not found at {alembic_ini}", err=True)
        raise SystemExit(1)

    cfg = AlembicConfig(alembic_ini)
    click.echo(f"Applying migrations -> {revision}")
    try:
        alembic_command.upgrade(cfg, revision)
        click.echo("Migrations applied")
    except Exception as e:
        click.echo(f"Migration failed: {e}", err=True)
        raise SystemExit(1)


@db.command("current")
def db_current():
    """Show the current database revision."""
    import os
    from alembic.config import Config as AlembicConfig
    from alembic import command as alembic_command

    alembic_ini = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "alembic.ini")
    )
    cfg = AlembicConfig(alembic_ini)
    alembic_command.current(cfg, verbose=True)


# =============================================================================
# Entry point
# =============================================================================


def main():
    """Main entry point."""
    cli(prog_name="mercury")


if __name__ == "__main__":
    main()

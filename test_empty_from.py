import asyncio
from mercury.app import create_app
from mercury.services.email.service import EmailService
from mercury.services.campaign_service import CampaignConfig
from mercury.services.smtp_service import SMTPService
from mercury.services.email.config import EmailConfig

async def main():
    app = create_app()
    with app.app_context():
        config = CampaignConfig(name="Test", chunk_size=10, concurrency=1, from_email="", from_name="")
        smtp_service = SMTPService()
        service = EmailService(smtp_service)
        service.configure(EmailConfig.from_campaign_config(config))
        
        try:
            res = await service.send_single(
                recipient="test@example.com",
                subject="Test",
                html_body="<html><body>Test</body></html>",
                from_email="",
                from_name=""
            )
            print("Result:", res)  # noqa: T201
            if not res.success:
                print("Error:", res.error)  # noqa: T201
        except Exception:
            import traceback
            traceback.print_exc()  # noqa: T201

asyncio.run(main())

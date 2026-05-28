import asyncio
from src.mercury.app import create_app
from src.mercury.engine.async_sender import AsyncEmailSender
from src.mercury.services.email.service import EmailService
from src.mercury.data.models.campaign import CampaignConfig

async def main():
    app = create_app()
    with app.app_context():
        config = CampaignConfig(name="Test", chunk_size=10, concurrency=1, from_email="", from_name="")
        service = EmailService(config)
        
        try:
            res = await service.send_single(
                recipient="test@example.com",
                subject="Test",
                html_body="<html><body>Test</body></html>",
                from_email="",
                from_name=""
            )
            print("Result:", res)
            if not res.success:
                print("Error:", res.error)
        except Exception as e:
            import traceback
            traceback.print_exc()

asyncio.run(main())

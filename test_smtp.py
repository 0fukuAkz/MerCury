import asyncio
from email.message import EmailMessage
import aiosmtplib

async def run():
    msg = EmailMessage()
    msg['From'] = ""
    msg['To'] = "test@example.com"
    msg['Subject'] = "test"
    msg.set_content("test")
    
    try:
        smtp = aiosmtplib.SMTP(hostname="127.0.0.1", port=25, timeout=2.0)
        # We don't even need to connect if extract_sender throws it immediately
        try:
            await smtp.send_message(msg)
        except Exception:
            import traceback
            traceback.print_exc()
    except Exception:
        import traceback
        traceback.print_exc()

asyncio.run(run())

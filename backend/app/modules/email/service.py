import logging
import resend
from typing import Optional
from app.config.settings import settings

logger = logging.getLogger(__name__)

class EmailService:
    def __init__(self):
        if settings.RESEND_API_KEY:
            resend.api_key = settings.RESEND_API_KEY
            self.configured = True
        else:
            self.configured = False
            logger.warning("RESEND_API_KEY not found. Emails will be logged but not sent.")

    def send_email(self, to_email: str, subject: str, html_body: str, from_email: str = "onboarding@resend.dev") -> bool:
        if not self.configured:
            logger.info(f"Mock sending email to {to_email} - Subject: {subject}")
            return True
            
        try:
            params = {
                "from": from_email,
                "to": [to_email],
                "subject": subject,
                "html": html_body,
            }
            response = resend.Emails.send(params)
            logger.info(f"Sent email to {to_email}: {response}")
            return True
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            return False

email_service = EmailService()

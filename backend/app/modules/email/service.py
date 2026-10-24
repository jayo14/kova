"""AWS SES email service integration with Sessy configuration set support."""

import logging
from typing import Any
import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.config.settings import settings

logger = logging.getLogger(__name__)


class EmailService:
    """Email delivery service using Amazon SES v2 with configuration set support."""

    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            region = settings.AWS_REGION or "eu-central-1"
            kwargs: dict[str, Any] = {
                "region_name": region,
            }
            if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
                kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
                kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY
            self._client = boto3.client("sesv2", **kwargs)
        return self._client

    @property
    def is_configured(self) -> bool:
        """True if credentials and sender are configured to allow sending."""
        has_keys = bool(settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY)
        has_sender = bool(settings.SES_FROM_EMAIL)
        return has_keys and has_sender

    def send_email(
        self,
        to_email: str,
        subject: str,
        html_body: str,
        from_email: str | None = None,
        configuration_set: str | None = None,
    ) -> bool:
        """Send an email using AWS SES v2.

        Passes configuration_set (e.g. 'production-ses') so Sessy / SNS receives
        delivery, open, click, bounce, and complaint events.
        """
        sender = from_email or settings.SES_FROM_EMAIL
        if not sender:
            err = "No sender email specified or configured in SES_FROM_EMAIL"
            logger.error(err)
            if settings.is_production:
                raise RuntimeError(f"Email delivery failed: {err}")
            return False

        config_set = configuration_set or settings.SES_CONFIGURATION_SET or "production-ses"

        if not self.is_configured:
            if settings.allow_mocks:
                logger.info(
                    "DEV mock sending email to %s (config_set=%s) - Subject: %s",
                    to_email,
                    config_set,
                    subject,
                )
                return True

            err = "AWS SES email service is not configured"
            if settings.is_production:
                err = "AWS SES email service is not configured in production (missing AWS credentials or SES_FROM_EMAIL)"
                logger.error(err)
                raise RuntimeError(err)

            logger.error("%s. Enable DEV_ALLOW_MOCKS for local development mocking.", err)
            return False

        try:
            params: dict[str, Any] = {
                "FromEmailAddress": sender,
                "Destination": {
                    "ToAddresses": [to_email],
                },
                "Content": {
                    "Simple": {
                        "Subject": {
                            "Data": subject,
                            "Charset": "UTF-8",
                        },
                        "Body": {
                            "Html": {
                                "Data": html_body,
                                "Charset": "UTF-8",
                            },
                        },
                    },
                },
            }
            if config_set:
                params["ConfigurationSetName"] = config_set

            response = self.client.send_email(**params)
            message_id = response.get("MessageId")
            logger.info(
                "Sent SES email to %s via %s (MessageId: %s)",
                to_email,
                config_set,
                message_id,
            )
            return True
        except (BotoCoreError, ClientError) as e:
            logger.error("Failed to send SES email to %s: %s", to_email, e)
            return False
        except Exception as e:
            logger.error("Unexpected error sending SES email to %s: %s", to_email, e)
            return False


email_service = EmailService()

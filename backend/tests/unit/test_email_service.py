from unittest.mock import MagicMock, patch
import pytest
from botocore.exceptions import ClientError, BotoCoreError

from app.config.settings import settings
from app.modules.email.service import EmailService


@pytest.fixture
def email_service_instance():
    return EmailService()


def test_email_service_unconfigured_mock_send(email_service_instance, monkeypatch):
    monkeypatch.setattr(settings, "AWS_ACCESS_KEY_ID", "")
    monkeypatch.setattr(settings, "AWS_SECRET_ACCESS_KEY", "")
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")

    assert email_service_instance.is_configured is False
    result = email_service_instance.send_email(
        to_email="user@example.com",
        subject="Test Subject",
        html_body="<p>Test</p>",
    )
    assert result is True


def test_email_service_sends_via_sesv2_with_configuration_set(email_service_instance, monkeypatch):
    monkeypatch.setattr(settings, "AWS_ACCESS_KEY_ID", "test-key-id")
    monkeypatch.setattr(settings, "AWS_SECRET_ACCESS_KEY", "test-secret-key")
    monkeypatch.setattr(settings, "AWS_REGION", "eu-central-1")
    monkeypatch.setattr(settings, "SES_CONFIGURATION_SET", "production-ses")
    monkeypatch.setattr(settings, "SES_FROM_EMAIL", "noreply@kova.app")

    assert email_service_instance.is_configured is True

    mock_boto_client = MagicMock()
    mock_boto_client.send_email.return_value = {"MessageId": "msg-ses-12345"}

    with patch("boto3.client", return_value=mock_boto_client) as mock_client_factory:
        result = email_service_instance.send_email(
            to_email="recipient@example.com",
            subject="Welcome to Kova",
            html_body="<h2>Welcome!</h2>",
        )

        assert result is True
        mock_client_factory.assert_called_once_with(
            "sesv2",
            region_name="eu-central-1",
            aws_access_key_id="test-key-id",
            aws_secret_access_key="test-secret-key",
        )
        mock_boto_client.send_email.assert_called_once_with(
            FromEmailAddress="noreply@kova.app",
            Destination={"ToAddresses": ["recipient@example.com"]},
            Content={
                "Simple": {
                    "Subject": {"Data": "Welcome to Kova", "Charset": "UTF-8"},
                    "Body": {"Html": {"Data": "<h2>Welcome!</h2>", "Charset": "UTF-8"}},
                }
            },
            ConfigurationSetName="production-ses",
        )


def test_email_service_custom_configuration_set_and_sender(email_service_instance, monkeypatch):
    monkeypatch.setattr(settings, "AWS_ACCESS_KEY_ID", "test-key")
    monkeypatch.setattr(settings, "AWS_SECRET_ACCESS_KEY", "test-secret")

    mock_boto_client = MagicMock()
    mock_boto_client.send_email.return_value = {"MessageId": "msg-custom-999"}

    with patch("boto3.client", return_value=mock_boto_client):
        result = email_service_instance.send_email(
            to_email="recipient@example.com",
            subject="Custom Alert",
            html_body="<p>Custom</p>",
            from_email="custom-sender@example.com",
            configuration_set="custom-config-set",
        )

        assert result is True
        _, kwargs = mock_boto_client.send_email.call_args
        assert kwargs["FromEmailAddress"] == "custom-sender@example.com"
        assert kwargs["ConfigurationSetName"] == "custom-config-set"


def test_email_service_handles_client_error(email_service_instance, monkeypatch):
    monkeypatch.setattr(settings, "AWS_ACCESS_KEY_ID", "test-key")
    monkeypatch.setattr(settings, "AWS_SECRET_ACCESS_KEY", "test-secret")

    mock_boto_client = MagicMock()
    error_response = {
        "Error": {
            "Code": "AccountSuspendedException",
            "Message": "Account suspended",
        }
    }
    mock_boto_client.send_email.side_effect = ClientError(error_response, "SendEmail")

    with patch("boto3.client", return_value=mock_boto_client):
        result = email_service_instance.send_email(
            to_email="fail@example.com",
            subject="Fail Subject",
            html_body="<p>Fail</p>",
        )
        assert result is False


def test_email_service_handles_botocore_error(email_service_instance, monkeypatch):
    monkeypatch.setattr(settings, "AWS_ACCESS_KEY_ID", "test-key")
    monkeypatch.setattr(settings, "AWS_SECRET_ACCESS_KEY", "test-secret")

    mock_boto_client = MagicMock()
    mock_boto_client.send_email.side_effect = BotoCoreError()

    with patch("boto3.client", return_value=mock_boto_client):
        result = email_service_instance.send_email(
            to_email="fail@example.com",
            subject="Fail Subject",
            html_body="<p>Fail</p>",
        )
        assert result is False

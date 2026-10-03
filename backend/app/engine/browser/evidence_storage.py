"""Evidence storage with S3 backend (RumptyCloud).

Stores evidence artifacts in a private S3 bucket. Returns short-lived signed URLs.
"""

import logging
import boto3
from botocore.exceptions import ClientError

from app.config.settings import settings

logger = logging.getLogger(__name__)


class EvidenceStorage:
    """Stores evidence in a private S3 bucket with signed URL access."""

    def __init__(self):
        self._bucket_ready = False
        self._s3_client = None

    def _get_s3_client(self):
        if not self._s3_client:
            self._s3_client = boto3.client(
                "s3",
                endpoint_url=settings.RUMPTYCLOUD_S3_ENDPOINT,
                aws_access_key_id=settings.RUMPTYCLOUD_ACCESS_KEY_ID,
                aws_secret_access_key=settings.RUMPTYCLOUD_SECRET_ACCESS_KEY,
                region_name="us-east-1",
            )
        return self._s3_client

    def _ensure_bucket(self):
        if self._bucket_ready:
            return

        if not settings.RUMPTYCLOUD_S3_ENDPOINT or not settings.RUMPTYCLOUD_ACCESS_KEY_ID:
            return

        bucket = settings.RUMPTYCLOUD_BUCKET_NAME or settings.storage_bucket("evidence")
        s3 = self._get_s3_client()

        try:
            s3.head_bucket(Bucket=bucket)
            self._bucket_ready = True
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code")
            if error_code == "404":
                try:
                    s3.create_bucket(Bucket=bucket)
                    self._bucket_ready = True
                    logger.info("Evidence storage bucket '%s' created", bucket)
                except Exception as ex:
                    logger.warning("Evidence bucket creation failed: %s", ex)
            else:
                logger.warning("Could not ensure evidence bucket: %s", e)
        except Exception as e:
            logger.warning("Could not ensure evidence bucket: %s", e)

    def upload(
        self,
        execution_id: str,
        evidence_id: str,
        data: bytes,
        content_type: str = "image/png",
    ) -> dict:
        """Upload evidence to S3. Returns {storage_key, url}."""
        if not settings.RUMPTYCLOUD_S3_ENDPOINT or not settings.RUMPTYCLOUD_ACCESS_KEY_ID:
            raise RuntimeError(
                "S3 storage not configured. "
                "Set RUMPTYCLOUD_S3_ENDPOINT and RUMPTYCLOUD_ACCESS_KEY_ID."
            )

        ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}.get(
            content_type, ".bin"
        )
        filename = f"{evidence_id}{ext}"
        object_path = f"executions/{execution_id}/evidence/{filename}"
        
        if settings.RUMPTYCLOUD_BUCKET_NAME:
            prefix = settings.storage_bucket("evidence")
            object_path = f"{prefix}/{object_path}"
            
        self._ensure_bucket()

        bucket = settings.RUMPTYCLOUD_BUCKET_NAME or settings.storage_bucket("evidence")
        s3 = self._get_s3_client()

        try:
            s3.put_object(
                Bucket=bucket,
                Key=object_path,
                Body=data,
                ContentType=content_type,
            )
            logger.debug("Uploaded evidence to S3: %s", object_path)
            return {
                "storage_key": object_path,
                "url": None,  # Use create_signed_url() for access
            }
        except Exception as e:
            raise RuntimeError(f"S3 evidence upload failed: {e}")

    def create_signed_url(self, storage_key: str, execution_id: str, expires_in: int = 3600) -> str | None:
        """Create a short-lived signed URL for secure evidence access."""
        if not settings.RUMPTYCLOUD_S3_ENDPOINT or not settings.RUMPTYCLOUD_ACCESS_KEY_ID:
            return None

        bucket = settings.RUMPTYCLOUD_BUCKET_NAME or settings.storage_bucket("evidence")
        s3 = self._get_s3_client()

        try:
            signed_url = s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": storage_key},
                ExpiresIn=expires_in,
            )
            return signed_url
        except Exception as e:
            logger.warning("Signed URL creation error: %s", e)

        return None

    def delete(self, storage_key: str) -> bool:
        """Delete evidence from storage."""
        if not settings.RUMPTYCLOUD_S3_ENDPOINT or not settings.RUMPTYCLOUD_ACCESS_KEY_ID:
            return False

        bucket = settings.RUMPTYCLOUD_BUCKET_NAME or settings.storage_bucket("evidence")
        s3 = self._get_s3_client()

        try:
            s3.delete_object(Bucket=bucket, Key=storage_key)
            return True
        except Exception as e:
            logger.warning("Evidence delete error: %s", e)
            return False


evidence_storage = EvidenceStorage()

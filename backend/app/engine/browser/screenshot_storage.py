"""Screenshot storage with S3 backend (RumptyCloud).

Uploads screenshots to a public S3 bucket.
"""

import logging
import uuid
import boto3
from botocore.exceptions import ClientError

from app.config.settings import settings

logger = logging.getLogger(__name__)


class ScreenshotStorage:
    """Stores screenshots in a public S3 bucket."""

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
        """Create the storage bucket if it doesn't exist (once per process)."""
        if self._bucket_ready:
            return

        if not settings.RUMPTYCLOUD_S3_ENDPOINT or not settings.RUMPTYCLOUD_ACCESS_KEY_ID:
            return

        bucket = settings.RUMPTYCLOUD_BUCKET_NAME or settings.storage_bucket("screenshots")
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
                    logger.info("Storage bucket '%s' created", bucket)
                except Exception as ex:
                    logger.warning("Bucket creation failed: %s", ex)
            else:
                logger.warning("Could not ensure storage bucket: %s", e)
        except Exception as e:
            logger.warning("Could not ensure storage bucket: %s", e)

    def save(
        self,
        exploration_id: str,
        screenshot_bytes: bytes,
        url: str = "",
        folder: str = "explorations",
        content_type: str = "image/png",
    ) -> dict:
        """Upload screenshot to S3 and return public URL.

        Returns metadata dict with screenshot_url and screenshot_key.
        Raises RuntimeError if S3 is not configured.
        """
        if not settings.RUMPTYCLOUD_S3_ENDPOINT or not settings.RUMPTYCLOUD_ACCESS_KEY_ID:
            raise RuntimeError(
                "S3 storage not configured. "
                "Set RUMPTYCLOUD_S3_ENDPOINT and RUMPTYCLOUD_ACCESS_KEY_ID environment variables."
            )

        ext = ".jpg" if "jpeg" in content_type or "jpg" in content_type else ".png"
        filename = f"{exploration_id}_{uuid.uuid4().hex[:12]}{ext}"
        object_path = f"{folder}/{exploration_id}/{filename}"
        self._ensure_bucket()

        # Fallback to older style if RUMPTYCLOUD_BUCKET_NAME is not provided
        bucket = settings.RUMPTYCLOUD_BUCKET_NAME or settings.storage_bucket("screenshots")
        # Prefix the object path with the logical bucket prefix if a unified bucket is used
        if settings.RUMPTYCLOUD_BUCKET_NAME:
            prefix = settings.storage_bucket("screenshots")
            object_path = f"{prefix}/{object_path}"
            
        s3 = self._get_s3_client()

        try:
            s3.put_object(
                Bucket=bucket,
                Key=object_path,
                Body=screenshot_bytes,
                ContentType=content_type,
            )
            # Use custom public URL prefix if available (e.g. assets.rumptycloud.app/...)
            if settings.RUMPTYCLOUD_PUBLIC_URL_PREFIX:
                public_url = f"{settings.RUMPTYCLOUD_PUBLIC_URL_PREFIX}/{object_path}"
            else:
                public_url = f"{settings.RUMPTYCLOUD_S3_ENDPOINT}/{bucket}/{object_path}"
            logger.debug("Uploaded screenshot to S3: %s", object_path)
            return {
                "screenshot_url": public_url,
                "screenshot_key": filename,
                "screenshot_size_bytes": len(screenshot_bytes),
            }
        except Exception as e:
            raise RuntimeError(f"S3 upload failed: {e}")

    def upload_execution_screenshot(
        self,
        execution_id: str,
        screenshot_bytes: bytes,
        url: str = "",
        content_type: str = "image/jpeg",
    ) -> dict:
        """Upload an execution screenshot safely to S3.

        Returns metadata dict. If upload fails or is not configured, logs warning
        and returns fallback dict without raising.
        """
        try:
            return self.save(
                exploration_id=execution_id,
                screenshot_bytes=screenshot_bytes,
                url=url,
                folder="executions",
                content_type=content_type,
            )
        except Exception as e:
            logger.warning("Could not upload execution screenshot to S3: %s", e)
            return {
                "screenshot_url": None,
                "screenshot_key": None,
                "screenshot_size_bytes": len(screenshot_bytes),
            }

    def get_public_url(self, key: str, exploration_id: str = "", folder: str = "explorations") -> str | None:
        """Get public URL for a screenshot key."""
        if not settings.RUMPTYCLOUD_S3_ENDPOINT or not exploration_id:
            return None
        object_path = f"{folder}/{exploration_id}/{key}"
        
        if settings.RUMPTYCLOUD_BUCKET_NAME:
            prefix = settings.storage_bucket("screenshots")
            object_path = f"{prefix}/{object_path}"
            
        if settings.RUMPTYCLOUD_PUBLIC_URL_PREFIX:
            return f"{settings.RUMPTYCLOUD_PUBLIC_URL_PREFIX}/{object_path}"
            
        bucket = settings.RUMPTYCLOUD_BUCKET_NAME or settings.storage_bucket("screenshots")
        return f"{settings.RUMPTYCLOUD_S3_ENDPOINT}/{bucket}/{object_path}"


# Singleton instance
screenshot_storage = ScreenshotStorage()

"""Screenshot storage with S3 backend (RumptyCloud).

Stores screenshots in a private S3 bucket with short-lived signed URLs (§Prompt D).
Never exposes unauthenticated public URLs for execution or exploration screenshots.
"""

import asyncio
import logging
import uuid
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.config.settings import settings

logger = logging.getLogger(__name__)


class ScreenshotStorage:
    """Stores screenshots in a private S3 bucket with short-lived signed URLs."""

    def __init__(self):
        self._bucket_ready = False
        self._s3_client = None

    def _get_s3_client(self):
        if not self._s3_client:
            s3_config = Config(
                connect_timeout=3,
                read_timeout=4,
                retries={"max_attempts": 2},
            )
            self._s3_client = boto3.client(
                "s3",
                endpoint_url=settings.RUMPTYCLOUD_S3_ENDPOINT,
                aws_access_key_id=settings.RUMPTYCLOUD_ACCESS_KEY_ID,
                aws_secret_access_key=settings.RUMPTYCLOUD_SECRET_ACCESS_KEY,
                region_name="us-east-1",
                config=s3_config,
            )
        return self._s3_client

    def _get_bucket_name(self) -> str:
        # Default to evidence private bucket or unified bucket
        return settings.RUMPTYCLOUD_BUCKET_NAME or settings.storage_bucket("evidence")

    def _ensure_bucket(self):
        """Create the storage bucket if it doesn't exist (once per process)."""
        if self._bucket_ready:
            return

        if not settings.RUMPTYCLOUD_S3_ENDPOINT or not settings.RUMPTYCLOUD_ACCESS_KEY_ID:
            return

        bucket = self._get_bucket_name()
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

    def create_signed_url(self, storage_key: str, expires_in: int = 3600) -> str | None:
        """Create a short-lived presigned URL for secure screenshot access."""
        if not settings.RUMPTYCLOUD_S3_ENDPOINT or not settings.RUMPTYCLOUD_ACCESS_KEY_ID:
            return None
        bucket = self._get_bucket_name()
        s3 = self._get_s3_client()
        try:
            return s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": storage_key},
                ExpiresIn=expires_in,
            )
        except Exception as e:
            logger.debug("Failed to create signed URL for %s: %s", storage_key, e)
            return None

    def save(
        self,
        exploration_id: str,
        screenshot_bytes: bytes,
        url: str = "",
        folder: str = "explorations",
        content_type: str = "image/png",
        purpose: str = "discovery",
        step_id: str | None = None,
    ) -> dict:
        """Upload screenshot to private S3 bucket and return signed URL."""
        if not settings.RUMPTYCLOUD_S3_ENDPOINT or not settings.RUMPTYCLOUD_ACCESS_KEY_ID:
            raise RuntimeError(
                "S3 storage not configured. "
                "Set RUMPTYCLOUD_S3_ENDPOINT and RUMPTYCLOUD_ACCESS_KEY_ID environment variables."
            )

        ext = ".jpg" if "jpeg" in content_type or "jpg" in content_type else ".png"
        filename = f"{exploration_id}_{uuid.uuid4().hex[:12]}{ext}"
        object_path = f"{folder}/{exploration_id}/{filename}"
        self._ensure_bucket()

        bucket = self._get_bucket_name()
        if settings.RUMPTYCLOUD_BUCKET_NAME:
            prefix = settings.storage_bucket("evidence")
            object_path = f"{prefix}/{object_path}"

        s3 = self._get_s3_client()

        try:
            s3.put_object(
                Bucket=bucket,
                Key=object_path,
                Body=screenshot_bytes,
                ContentType=content_type,
            )
            signed_url = self.create_signed_url(object_path, expires_in=3600)
            logger.debug("Uploaded private screenshot to S3: %s", object_path)
            return {
                "screenshot_url": signed_url,
                "screenshot_key": object_path,
                "screenshot_size_bytes": len(screenshot_bytes),
                "purpose": purpose,
                "step_id": step_id,
            }
        except Exception as e:
            raise RuntimeError(f"S3 upload failed: {e}")

    async def save_async(
        self,
        exploration_id: str,
        screenshot_bytes: bytes,
        url: str = "",
        folder: str = "explorations",
        content_type: str = "image/png",
        purpose: str = "discovery",
        step_id: str | None = None,
        max_retries: int = 3,
    ) -> dict:
        """Asynchronously upload screenshot with retries and exponential backoff."""
        if not settings.RUMPTYCLOUD_S3_ENDPOINT or not settings.RUMPTYCLOUD_ACCESS_KEY_ID:
            return {
                "screenshot_url": None,
                "screenshot_key": None,
                "screenshot_size_bytes": len(screenshot_bytes),
                "purpose": purpose,
                "step_id": step_id,
                "status": "FAILED",
                "error": "S3 not configured",
            }

        last_error = None
        for attempt in range(max_retries):
            try:
                res = await asyncio.to_thread(
                    self.save,
                    exploration_id=exploration_id,
                    screenshot_bytes=screenshot_bytes,
                    url=url,
                    folder=folder,
                    content_type=content_type,
                    purpose=purpose,
                    step_id=step_id,
                )
                res["status"] = "UPLOADED"
                return res
            except Exception as e:
                last_error = e
                backoff = 0.25 * (2 ** attempt)
                logger.warning(
                    "Screenshot upload attempt %d/%d failed for %s: %s; retrying in %.2fs",
                    attempt + 1, max_retries, exploration_id, e, backoff,
                )
                await asyncio.sleep(backoff)

        logger.warning("All %d screenshot upload attempts failed for %s: %s", max_retries, exploration_id, last_error)
        return {
            "screenshot_url": None,
            "screenshot_key": None,
            "screenshot_size_bytes": len(screenshot_bytes),
            "purpose": purpose,
            "step_id": step_id,
            "status": "FAILED",
            "error": str(last_error),
        }

    def upload_execution_screenshot(
        self,
        execution_id: str,
        screenshot_bytes: bytes,
        url: str = "",
        content_type: str = "image/jpeg",
        purpose: str = "step_evidence",
        step_id: str | None = None,
    ) -> dict:
        """Upload an execution screenshot safely to private S3 and return signed URL."""
        try:
            return self.save(
                exploration_id=execution_id,
                screenshot_bytes=screenshot_bytes,
                url=url,
                folder="executions",
                content_type=content_type,
                purpose=purpose,
                step_id=step_id,
            )
        except Exception as e:
            logger.warning("Could not upload execution screenshot to S3: %s", e)
            return {
                "screenshot_url": None,
                "screenshot_key": None,
                "screenshot_size_bytes": len(screenshot_bytes),
                "purpose": purpose,
                "step_id": step_id,
                "status": "FAILED",
                "error": str(e),
            }

    def get_public_url(self, key: str, exploration_id: str = "", folder: str = "explorations") -> str | None:
        """Alias for secure signed URL retrieval (guarantees signed access)."""
        object_path = key
        if exploration_id and not key.startswith(f"{folder}/{exploration_id}/"):
            object_path = f"{folder}/{exploration_id}/{key}"
            if settings.RUMPTYCLOUD_BUCKET_NAME:
                prefix = settings.storage_bucket("evidence")
                object_path = f"{prefix}/{object_path}"
        return self.create_signed_url(object_path)


# Singleton instance
screenshot_storage = ScreenshotStorage()

"""Screenshot storage with Supabase Storage backend.

Uploads screenshots to a public Supabase Storage bucket.
Requires Supabase to be configured; raises on missing credentials.
"""

import logging
import uuid

import httpx

from app.config.settings import settings

logger = logging.getLogger(__name__)


class ScreenshotStorage:
    """Stores screenshots in a public Supabase Storage bucket."""

    def __init__(self):
        self._bucket_ready = False

    def _ensure_bucket(self):
        """Create the storage bucket if it doesn't exist (once per process)."""
        if self._bucket_ready:
            return

        bucket = settings.storage_bucket("screenshots")

        try:
            resp = httpx.post(
                f"{settings.supabase_url}/storage/v1/bucket",
                headers={
                    "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "id": bucket,
                    "name": bucket,
                    "public": True,
                    "file_size_limit": 5 * 1024 * 1024,  # 5MB
                    "allowed_mime_types": ["image/png", "image/jpeg", "image/webp"],
                },
                timeout=5,
            )
            if resp.status_code in (200, 201):
                self._bucket_ready = True
                logger.info("Storage bucket '%s' created", bucket)
            else:
                body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                if resp.status_code == 400 and body.get("code") == "BucketAlreadyExists":
                    self._bucket_ready = True
                    logger.debug("Storage bucket '%s' already exists", bucket)
                elif resp.status_code == 409:
                    self._bucket_ready = True
                    logger.debug("Storage bucket '%s' already exists", bucket)
                else:
                    logger.warning("Bucket creation failed (%d): %s", resp.status_code, resp.text[:200])
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
        """Upload screenshot to Supabase Storage and return public URL.

        Returns metadata dict with screenshot_url and screenshot_key.
        Raises RuntimeError if Supabase is not configured.
        """
        if not settings.supabase_url or not settings.SUPABASE_SERVICE_ROLE_KEY:
            raise RuntimeError(
                "Supabase storage not configured. "
                "Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY environment variables."
            )

        ext = ".jpg" if "jpeg" in content_type or "jpg" in content_type else ".png"
        filename = f"{exploration_id}_{uuid.uuid4().hex[:12]}{ext}"
        object_path = f"{folder}/{exploration_id}/{filename}"
        self._ensure_bucket()

        bucket = settings.storage_bucket("screenshots")
        resp = httpx.post(
            f"{settings.supabase_url}/storage/v1/object/{bucket}/{object_path}",
            headers={
                "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
                "Content-Type": content_type,
                "x-upsert": "true",
            },
            content=screenshot_bytes,
            timeout=10,
        )

        if resp.status_code in (200, 201):
            public_url = (
                f"{settings.supabase_url}/storage/v1/object/public/"
                f"{bucket}/{object_path}"
            )
            logger.debug("Uploaded screenshot to Supabase: %s", object_path)
            return {
                "screenshot_url": public_url,
                "screenshot_key": filename,
                "screenshot_size_bytes": len(screenshot_bytes),
            }
        else:
            raise RuntimeError(
                f"Supabase upload failed ({resp.status_code}): {resp.text[:200]}"
            )

    def upload_execution_screenshot(
        self,
        execution_id: str,
        screenshot_bytes: bytes,
        url: str = "",
        content_type: str = "image/jpeg",
    ) -> dict:
        """Upload an execution screenshot safely to Supabase Storage.

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
            logger.warning("Could not upload execution screenshot to Supabase: %s", e)
            return {
                "screenshot_url": None,
                "screenshot_key": None,
                "screenshot_size_bytes": len(screenshot_bytes),
            }

    def get_public_url(self, key: str, exploration_id: str = "", folder: str = "explorations") -> str | None:
        """Get public URL for a screenshot key."""
        if not settings.supabase_url or not exploration_id:
            return None
        bucket = settings.storage_bucket("screenshots")
        object_path = f"{folder}/{exploration_id}/{key}"
        return (
            f"{settings.supabase_url}/storage/v1/object/public/"
            f"{bucket}/{object_path}"
        )


# Singleton instance
screenshot_storage = ScreenshotStorage()

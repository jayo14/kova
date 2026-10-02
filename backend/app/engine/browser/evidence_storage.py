"""Evidence storage with Supabase Storage backend.

Stores evidence artifacts (screenshots, verification data) in a private
Supabase Storage bucket. Returns short-lived signed URLs for secure access.
Requires Supabase to be configured; raises on missing credentials.
"""

import logging
import uuid

import httpx

from app.config.settings import settings

logger = logging.getLogger(__name__)


class EvidenceStorage:
    """Stores evidence in a private Supabase Storage bucket with signed URL access."""

    def __init__(self):
        self._bucket_ready = False

    def _ensure_bucket(self):
        if self._bucket_ready:
            return

        bucket = settings.storage_bucket("evidence")

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
                    "public": False,
                    "file_size_limit": 10 * 1024 * 1024,  # 10MB
                    "allowed_mime_types": [
                        "image/png", "image/jpeg", "image/webp",
                        "application/json", "text/plain",
                    ],
                },
                timeout=10,
            )
            if resp.status_code in (200, 201):
                self._bucket_ready = True
                logger.info("Evidence storage bucket '%s' created", bucket)
            else:
                body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                if resp.status_code == 400 and body.get("code") == "BucketAlreadyExists":
                    self._bucket_ready = True
                elif resp.status_code == 409:
                    self._bucket_ready = True
                else:
                    logger.warning("Evidence bucket creation failed (%d): %s", resp.status_code, resp.text[:200])
        except Exception as e:
            logger.warning("Could not ensure evidence bucket: %s", e)

    def upload(
        self,
        execution_id: str,
        evidence_id: str,
        data: bytes,
        content_type: str = "image/png",
    ) -> dict:
        """Upload evidence to Supabase Storage. Returns {storage_key, url}.

        Raises RuntimeError if Supabase is not configured.
        """
        if not settings.supabase_url or not settings.SUPABASE_SERVICE_ROLE_KEY:
            raise RuntimeError(
                "Supabase storage not configured. "
                "Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY environment variables."
            )
        if not settings.supabase_url.startswith("https://"):
            raise RuntimeError(
                "Evidence storage requires HTTPS. "
                f"Current URL: {settings.supabase_url}"
            )

        ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}.get(
            content_type, ".bin"
        )
        filename = f"{evidence_id}{ext}"
        object_path = f"executions/{execution_id}/evidence/{filename}"
        self._ensure_bucket()

        bucket = settings.storage_bucket("evidence")
        resp = httpx.post(
            f"{settings.supabase_url}/storage/v1/object/{bucket}/{object_path}",
            headers={
                "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
                "Content-Type": content_type,
                "x-upsert": "true",
            },
            content=data,
            timeout=30,
        )

        if resp.status_code in (200, 201):
            logger.debug("Uploaded evidence to Supabase: %s", object_path)
            return {
                "storage_key": object_path,
                "url": None,  # Use create_signed_url() for access
            }
        else:
            raise RuntimeError(
                f"Supabase evidence upload failed ({resp.status_code}): {resp.text[:200]}"
            )

    def create_signed_url(self, storage_key: str, execution_id: str, expires_in: int = 3600) -> str | None:
        """Create a short-lived signed URL for secure evidence access.

        Args:
            storage_key: The storage path/key for the evidence file.
            execution_id: The execution ID (used for Supabase path construction).
            expires_in: URL validity in seconds (default 1 hour).

        Returns:
            Signed URL string, or None if Supabase is not configured.
        """
        if not settings.supabase_url or not settings.SUPABASE_SERVICE_ROLE_KEY:
            return None

        bucket = settings.storage_bucket("evidence")

        try:
            resp = httpx.post(
                f"{settings.supabase_url}/storage/v1/object/sign/{bucket}/{storage_key}",
                headers={
                    "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
                    "Content-Type": "application/json",
                },
                json={"expiresIn": expires_in},
                timeout=10,
            )

            if resp.status_code == 200:
                data = resp.json()
                signed_url = data.get("signedURL") or data.get("signedUrl", "")
                if signed_url:
                    if signed_url.startswith("/"):
                        # Supabase returns /object/sign/... but full URL
                        # needs /storage/v1/object/sign/...
                        if not signed_url.startswith("/storage/"):
                            signed_url = f"/storage/v1{signed_url}"
                        signed_url = f"{settings.supabase_url.rstrip('/')}{signed_url}"
                    return signed_url
            else:
                logger.warning("Signed URL creation failed (%d): %s", resp.status_code, resp.text[:200])
        except Exception as e:
            logger.warning("Signed URL creation error: %s", e)

        return None

    def delete(self, storage_key: str) -> bool:
        """Delete evidence from storage."""
        if not settings.supabase_url or not settings.SUPABASE_SERVICE_ROLE_KEY:
            return False

        bucket = settings.storage_bucket("evidence")

        try:
            resp = httpx.delete(
                f"{settings.supabase_url}/storage/v1/object/{bucket}/{storage_key}",
                headers={
                    "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
                },
                timeout=10,
            )
            return resp.status_code in (200, 204)
        except Exception as e:
            logger.warning("Evidence delete error: %s", e)
            return False


evidence_storage = EvidenceStorage()

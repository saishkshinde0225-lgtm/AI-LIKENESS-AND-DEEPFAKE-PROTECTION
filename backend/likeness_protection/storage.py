"""
AssetStorage — thin wrapper around MinIO.

Design decisions
----------------
- This class is the *only* place that imports minio.  Repository and
  service layers depend on it via constructor injection so tests can
  substitute a fake.
- Object keys never contain PII.
  Pattern:  identities/{identity_id}/face/{asset_id}
- The bucket is always private; access is through presigned GET URLs.
- All minio exceptions are caught here and re-raised as
  StorageUnavailableError so callers only ever see domain exceptions.
- Presigned URL TTL defaults to 5 minutes (300 seconds).
"""

from __future__ import annotations

import logging
from datetime import timedelta

from minio import Minio
from minio.error import S3Error

from likeness_protection.errors import StorageUnavailableError

logger = logging.getLogger(__name__)

_DEFAULT_PRESIGN_TTL_SECONDS = 300


class AssetStorage:
    """Concrete MinIO wrapper.

    Parameters
    ----------
    client:
        A configured minio.Minio instance (endpoint, credentials, TLS).
    bucket:
        The private bucket that holds face assets.
    presign_ttl_seconds:
        Lifetime of presigned GET URLs in seconds.
    """

    def __init__(
        self,
        client: Minio,
        bucket: str,
        presign_ttl_seconds: int = _DEFAULT_PRESIGN_TTL_SECONDS,
    ) -> None:
        self._client = client
        self._bucket = bucket
        self._ttl = presign_ttl_seconds

    # ── Public API ────────────────────────────────────────────────────────────

    def put(self, object_key: str, data: bytes, content_type: str = "image/jpeg") -> None:
        """Upload *data* to *object_key*.

        Raises StorageUnavailableError on any MinIO error.
        """
        import io

        try:
            self._client.put_object(
                bucket_name=self._bucket,
                object_name=object_key,
                data=io.BytesIO(data),
                length=len(data),
                content_type=content_type,
            )
        except S3Error as exc:
            logger.error("minio put failed key=%s error=%s", object_key, exc)
            raise StorageUnavailableError() from exc
        except Exception as exc:
            logger.error("minio put unexpected error key=%s error=%s", object_key, exc)
            raise StorageUnavailableError() from exc

    def delete(self, object_key: str) -> None:
        """Delete *object_key*.

        Idempotent: a missing key is not an error (S3 semantics).
        Raises StorageUnavailableError on connectivity / permission errors.
        """
        try:
            self._client.remove_object(
                bucket_name=self._bucket,
                object_name=object_key,
            )
        except S3Error as exc:
            if exc.code == "NoSuchKey":
                logger.warning("minio delete: key already absent key=%s", object_key)
                return
            logger.error("minio delete failed key=%s error=%s", object_key, exc)
            raise StorageUnavailableError() from exc
        except Exception as exc:
            logger.error("minio delete unexpected error key=%s error=%s", object_key, exc)
            raise StorageUnavailableError() from exc

    def presign_get(self, object_key: str) -> tuple[str, int]:
        """Return a presigned GET URL and its TTL in seconds.

        Returns
        -------
        (url, ttl_seconds)

        Raises StorageUnavailableError on failure.
        """
        try:
            url: str = self._client.presigned_get_object(
                bucket_name=self._bucket,
                object_name=object_key,
                expires=timedelta(seconds=self._ttl),
            )
            return url, self._ttl
        except S3Error as exc:
            logger.error("minio presign failed key=%s error=%s", object_key, exc)
            raise StorageUnavailableError() from exc
        except Exception as exc:
            logger.error("minio presign unexpected error key=%s error=%s", object_key, exc)
            raise StorageUnavailableError() from exc

    # ── Key helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def make_face_key(identity_id: str, asset_id: str) -> str:
        """Canonical object key for a face asset.

        identities/{identity_id}/face/{asset_id}

        No PII, no extension (content-type is stored on the object).
        """
        return f"identities/{identity_id}/face/{asset_id}"

    def ensure_bucket_exists(self) -> None:
        """Create the bucket if it doesn't exist.

        Call once at application startup.
        """
        try:
            if not self._client.bucket_exists(self._bucket):
                self._client.make_bucket(self._bucket)
                logger.info("created minio bucket=%s", self._bucket)
        except S3Error as exc:
            logger.error("minio bucket setup failed bucket=%s error=%s", self._bucket, exc)
            raise StorageUnavailableError() from exc

"""Tests for storage.py — AssetStorage using a fake MinIO client."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from minio.error import S3Error

from likeness_protection.errors import StorageUnavailableError
from likeness_protection.storage import AssetStorage


def _make_storage(client=None) -> tuple[AssetStorage, MagicMock]:
    mock_client = client or MagicMock()
    return AssetStorage(client=mock_client, bucket="test-bucket"), mock_client


class TestMakeFaceKey:
    def test_key_format(self):
        key = AssetStorage.make_face_key("identity123", "asset456")
        assert key == "identities/identity123/face/asset456"

    def test_key_contains_no_pii(self):
        key = AssetStorage.make_face_key("id1", "a1")
        # No name, email, or other PII in the key path.
        assert key.startswith("identities/")


class TestPut:
    def test_successful_put(self):
        storage, mock_client = _make_storage()
        mock_client.put_object.return_value = None
        storage.put("identities/id/face/asset", b"fake_jpeg_data")
        mock_client.put_object.assert_called_once()

    def test_s3_error_raises_storage_unavailable(self):
        storage, mock_client = _make_storage()
        mock_client.put_object.side_effect = S3Error(
            MagicMock(), "InternalError", "server error", "", "", ""
        )
        with pytest.raises(StorageUnavailableError):
            storage.put("key", b"data")

    def test_generic_exception_raises_storage_unavailable(self):
        storage, mock_client = _make_storage()
        mock_client.put_object.side_effect = ConnectionError("timeout")
        with pytest.raises(StorageUnavailableError):
            storage.put("key", b"data")


class TestDelete:
    def test_successful_delete(self):
        storage, mock_client = _make_storage()
        mock_client.remove_object.return_value = None
        storage.delete("identities/id/face/asset")
        mock_client.remove_object.assert_called_once()

    def test_no_such_key_is_silent(self):
        storage, mock_client = _make_storage()
        # S3Error(response, code, message, resource, request_id, host_id)
        mock_client.remove_object.side_effect = S3Error(
            MagicMock(), "NoSuchKey", "key not found", "", "", ""
        )
        # Should not raise — idempotent delete.
        storage.delete("missing-key")

    def test_s3_error_non_404_raises(self):
        storage, mock_client = _make_storage()
        mock_client.remove_object.side_effect = S3Error(
            MagicMock(), "AccessDenied", "denied", "", "", ""
        )
        with pytest.raises(StorageUnavailableError):
            storage.delete("key")


class TestPresignGet:
    def test_successful_presign(self):
        storage, mock_client = _make_storage()
        mock_client.presigned_get_object.return_value = "https://minio.example.com/signed"
        url, ttl = storage.presign_get("identities/id/face/asset")
        assert url.startswith("https://")
        assert ttl == 300  # default TTL

    def test_custom_ttl_respected(self):
        mock_client = MagicMock()
        mock_client.presigned_get_object.return_value = "https://example.com/url"
        storage = AssetStorage(mock_client, "bucket", presign_ttl_seconds=60)
        _, ttl = storage.presign_get("key")
        assert ttl == 60

    def test_s3_error_raises_unavailable(self):
        storage, mock_client = _make_storage()
        mock_client.presigned_get_object.side_effect = S3Error(
            MagicMock(), "InternalError", "err", "", "", ""
        )
        with pytest.raises(StorageUnavailableError):
            storage.presign_get("key")

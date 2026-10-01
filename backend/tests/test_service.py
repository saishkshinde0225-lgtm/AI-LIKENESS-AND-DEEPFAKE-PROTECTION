"""
Tests for service.py — IdentityService and ConsentService.

All MongoDB and MinIO calls are replaced with AsyncMock / MagicMock fakes.
No network I/O occurs.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image

from likeness_protection.domain.documents import (
    ConsentPolicyDoc,
    EmbeddingDoc,
    FaceAssetDoc,
    ProtectedIdentityDoc,
)
from likeness_protection.domain.enums import (
    EmbeddingState,
    FaceAssetState,
    IdentityStatus,
    PermittedUse,
)
from likeness_protection.errors import (
    ConsentInconsistentError,
    DuplicateIdentityError,
    IdentityWithdrawnError,
)
from likeness_protection.schemas import (
    ConsentRevokeRequest,
    ConsentUpdateRequest,
    IdentityRegisterForm,
)
from likeness_protection.service import ConsentService, IdentityService

# ── Fixtures ──────────────────────────────────────────────────────────────────

_NOW = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
_OWNER = "owner-abc"
_IDENTITY_ID = "6660000000000000000000aa"
_ASSET_ID = "6660000000000000000000bb"


def _make_jpeg(width: int = 400, height: int = 400) -> bytes:
    img = Image.new("RGB", (width, height), color=(10, 20, 30))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _face_asset(state: FaceAssetState = FaceAssetState.STORED) -> FaceAssetDoc:
    return FaceAssetDoc(
        bucket="bucket",
        object_key=f"identities/{_IDENTITY_ID}/face/{_ASSET_ID}",
        content_type="image/jpeg",
        size_bytes=1024,
        sha256="abc123",
        width=400,
        height=400,
        uploaded_at=_NOW,
        state=state,
    )


def _identity(status: IdentityStatus = IdentityStatus.ACTIVE) -> ProtectedIdentityDoc:
    return ProtectedIdentityDoc(
        id=_IDENTITY_ID,
        owner_id=_OWNER,
        display_name="Alice",
        status=status,
        face_asset=_face_asset(),
        embedding=EmbeddingDoc(state=EmbeddingState.NOT_GENERATED),
        created_at=_NOW,
        updated_at=_NOW,
        withdrawn_at=None if status == IdentityStatus.ACTIVE else _NOW,
    )


def _consent(status: str = "active") -> ConsentPolicyDoc:
    return ConsentPolicyDoc(
        id="consent-id",
        identity_id=_IDENTITY_ID,
        owner_id=_OWNER,
        biometric_granted=True,
        biometric_notice_version="v1.0",
        biometric_granted_at=_NOW,
        permitted_uses=[PermittedUse.NEWS_REPORTING],
        status=status,
        version=1,
        history=[],
        created_at=_NOW,
        updated_at=_NOW,
    )


def _make_service() -> tuple[IdentityService, MagicMock, MagicMock, MagicMock]:
    identity_repo = MagicMock()
    consent_repo = MagicMock()
    storage = MagicMock()
    svc = IdentityService(
        identity_repo=identity_repo,
        consent_repo=consent_repo,
        storage=storage,
    )
    return svc, identity_repo, consent_repo, storage


# ── IdentityService.register ──────────────────────────────────────────────────


class TestRegister:
    @pytest.mark.asyncio
    async def test_successful_registration(self):
        svc, identity_repo, consent_repo, storage = _make_service()

        identity_repo.find_active_by_sha256 = AsyncMock(return_value=None)
        identity_repo.insert_with_id = AsyncMock(return_value=_identity())
        consent_repo.insert = AsyncMock(return_value=_consent())
        storage.put = MagicMock()

        form = IdentityRegisterForm(
            display_name="Alice",
            biometric_consent=True,
            consent_notice_version="v1.0",
            permitted_uses=[PermittedUse.NEWS_REPORTING],
        )

        result, is_replay = await svc.register(
            owner_id=_OWNER,
            form=form,
            raw_image=_make_jpeg(),
        )

        assert is_replay is False
        assert result.display_name == "Alice"
        storage.put.assert_called_once()

    @pytest.mark.asyncio
    async def test_exact_replay_returns_is_replay_true(self):
        svc, identity_repo, consent_repo, storage = _make_service()

        existing = _identity()
        existing_consent = _consent()
        identity_repo.find_active_by_sha256 = AsyncMock(return_value=existing)
        consent_repo.get_for_identity = AsyncMock(return_value=existing_consent)

        form = IdentityRegisterForm(
            display_name="Alice",           # same as existing
            biometric_consent=True,
            consent_notice_version="v1.0",  # same as existing
            permitted_uses=[PermittedUse.NEWS_REPORTING],  # same as existing
        )

        result, is_replay = await svc.register(
            owner_id=_OWNER,
            form=form,
            raw_image=_make_jpeg(),
        )

        assert is_replay is True
        storage.put.assert_not_called()

    @pytest.mark.asyncio
    async def test_duplicate_different_metadata_raises(self):
        svc, identity_repo, consent_repo, storage = _make_service()

        existing = _identity()
        existing_consent = _consent()
        identity_repo.find_active_by_sha256 = AsyncMock(return_value=existing)
        consent_repo.get_for_identity = AsyncMock(return_value=existing_consent)

        form = IdentityRegisterForm(
            display_name="Bob",             # different display_name = conflict
            biometric_consent=True,
            consent_notice_version="v1.0",
            permitted_uses=[PermittedUse.NEWS_REPORTING],
        )

        with pytest.raises(DuplicateIdentityError) as exc_info:
            await svc.register(
                owner_id=_OWNER,
                form=form,
                raw_image=_make_jpeg(),
            )
        assert exc_info.value.details["existing_identity_id"] == _IDENTITY_ID

    @pytest.mark.asyncio
    async def test_minio_failure_propagates_and_no_db_write(self):
        from likeness_protection.errors import StorageUnavailableError

        svc, identity_repo, consent_repo, storage = _make_service()
        identity_repo.find_active_by_sha256 = AsyncMock(return_value=None)
        storage.put = MagicMock(side_effect=StorageUnavailableError())

        form = IdentityRegisterForm(
            display_name="Alice",
            biometric_consent=True,
            consent_notice_version="v1.0",
        )

        with pytest.raises(StorageUnavailableError):
            await svc.register(
                owner_id=_OWNER,
                form=form,
                raw_image=_make_jpeg(),
            )

        # DB insert must not be called if MinIO upload failed.
        identity_repo.insert_with_id.assert_not_called()

    @pytest.mark.asyncio
    async def test_db_failure_after_upload_triggers_best_effort_delete(self):
        svc, identity_repo, consent_repo, storage = _make_service()
        identity_repo.find_active_by_sha256 = AsyncMock(return_value=None)
        storage.put = MagicMock()
        storage.delete = MagicMock()
        consent_repo.insert = AsyncMock(side_effect=Exception("mongo timeout"))

        form = IdentityRegisterForm(
            display_name="Alice",
            biometric_consent=True,
            consent_notice_version="v1.0",
        )

        with pytest.raises(Exception, match="mongo timeout"):
            await svc.register(
                owner_id=_OWNER,
                form=form,
                raw_image=_make_jpeg(),
            )

        # MinIO delete must have been attempted.
        storage.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_missing_consent_on_existing_raises_inconsistent(self):
        svc, identity_repo, consent_repo, storage = _make_service()
        identity_repo.find_active_by_sha256 = AsyncMock(return_value=_identity())
        consent_repo.get_for_identity = AsyncMock(return_value=None)

        form = IdentityRegisterForm(
            display_name="Alice",
            biometric_consent=True,
            consent_notice_version="v1.0",
        )

        with pytest.raises(ConsentInconsistentError):
            await svc.register(owner_id=_OWNER, form=form, raw_image=_make_jpeg())


# ── IdentityService.withdraw ──────────────────────────────────────────────────


class TestWithdraw:
    @pytest.mark.asyncio
    async def test_happy_path_withdraw(self):
        svc, identity_repo, consent_repo, storage = _make_service()

        withdrawn = ProtectedIdentityDoc(
            id=_IDENTITY_ID,
            owner_id=_OWNER,
            display_name="Alice",
            status=IdentityStatus.WITHDRAWN,
            face_asset=_face_asset(FaceAssetState.PURGE_PENDING),
            embedding=EmbeddingDoc(),
            created_at=_NOW,
            updated_at=_NOW,
            withdrawn_at=_NOW,
        )
        purged_identity = ProtectedIdentityDoc(
            id=_IDENTITY_ID,
            owner_id=_OWNER,
            display_name="Alice",
            status=IdentityStatus.WITHDRAWN,
            face_asset=FaceAssetDoc(
                bucket="bucket",
                object_key=None,
                sha256=None,
                content_type="image/jpeg",
                size_bytes=1024,
                width=400,
                height=400,
                uploaded_at=_NOW,
                state=FaceAssetState.PURGED,
            ),
            embedding=EmbeddingDoc(),
            created_at=_NOW,
            updated_at=_NOW,
            withdrawn_at=_NOW,
        )

        identity_repo.mark_withdrawn = AsyncMock(return_value=withdrawn)
        consent_repo.revoke = AsyncMock(return_value=_consent(status="revoked"))
        storage.delete = MagicMock()
        identity_repo.mark_asset_purged = AsyncMock()
        identity_repo.get = AsyncMock(return_value=purged_identity)

        result = await svc.withdraw(identity_id=_IDENTITY_ID, owner_id=_OWNER)

        assert result.status == IdentityStatus.WITHDRAWN.value
        storage.delete.assert_called_once()
        identity_repo.mark_asset_purged.assert_called_once()

    @pytest.mark.asyncio
    async def test_minio_failure_still_returns_withdrawn(self):
        from likeness_protection.errors import StorageUnavailableError

        svc, identity_repo, consent_repo, storage = _make_service()

        withdrawn = ProtectedIdentityDoc(
            id=_IDENTITY_ID, owner_id=_OWNER, display_name="Alice",
            status=IdentityStatus.WITHDRAWN,
            face_asset=_face_asset(FaceAssetState.PURGE_PENDING),
            embedding=EmbeddingDoc(), created_at=_NOW, updated_at=_NOW,
            withdrawn_at=_NOW,
        )
        identity_repo.mark_withdrawn = AsyncMock(return_value=withdrawn)
        consent_repo.revoke = AsyncMock(return_value=_consent(status="revoked"))
        storage.delete = MagicMock(side_effect=StorageUnavailableError())

        # Should not raise; MinIO failure is logged and withdrawal stays effective.
        result = await svc.withdraw(identity_id=_IDENTITY_ID, owner_id=_OWNER)
        assert result.status == IdentityStatus.WITHDRAWN.value
        # mark_asset_purged NOT called — purge_pending stays for reaper.
        identity_repo.mark_asset_purged.assert_not_called()


# ── ConsentService.update_consent ─────────────────────────────────────────────


class TestUpdateConsent:
    @pytest.mark.asyncio
    async def test_update_on_active_identity(self):
        identity_repo = MagicMock()
        consent_repo = MagicMock()
        identity_svc = MagicMock()
        svc = ConsentService(identity_repo, consent_repo, identity_svc)

        identity_repo.get = AsyncMock(return_value=_identity())
        updated_consent = _consent()
        updated_consent.permitted_uses = [PermittedUse.EDUCATIONAL]
        updated_consent.version = 2
        consent_repo.update_permitted_uses = AsyncMock(return_value=updated_consent)

        req = ConsentUpdateRequest(
            permitted_uses=[PermittedUse.EDUCATIONAL],
            expected_version=1,
        )
        result = await svc.update_consent(
            identity_id=_IDENTITY_ID, owner_id=_OWNER, request=req
        )
        assert result.version == 2

    @pytest.mark.asyncio
    async def test_update_on_withdrawn_identity_raises(self):
        identity_repo = MagicMock()
        consent_repo = MagicMock()
        identity_svc = MagicMock()
        svc = ConsentService(identity_repo, consent_repo, identity_svc)

        identity_repo.get = AsyncMock(return_value=_identity(IdentityStatus.WITHDRAWN))

        with pytest.raises(IdentityWithdrawnError):
            await svc.update_consent(
                identity_id=_IDENTITY_ID,
                owner_id=_OWNER,
                request=ConsentUpdateRequest(permitted_uses=[], expected_version=1),
            )


# ── ConsentService.revoke_consent ─────────────────────────────────────────────


class TestRevokeConsent:
    @pytest.mark.asyncio
    async def test_revoke_delegates_to_identity_service_withdraw(self):
        identity_repo = MagicMock()
        consent_repo = MagicMock()
        identity_svc = MagicMock()
        svc = ConsentService(identity_repo, consent_repo, identity_svc)

        identity_repo.get = AsyncMock(return_value=_identity())
        identity_svc.withdraw = AsyncMock(return_value=MagicMock())

        await svc.revoke_consent(
            identity_id=_IDENTITY_ID,
            owner_id=_OWNER,
            request=ConsentRevokeRequest(reason="test"),
        )

        identity_svc.withdraw.assert_called_once_with(
            identity_id=_IDENTITY_ID,
            owner_id=_OWNER,
            revoke_reason="test",
        )

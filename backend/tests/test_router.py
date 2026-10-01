"""
Router integration tests.

Uses FastAPI TestClient.  Services are replaced with AsyncMock so no
real MongoDB or MinIO is needed.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from likeness_protection.deps import (
    get_consent_service,
    get_identity_service,
)
from likeness_protection.domain.enums import (
    EmbeddingState,
    FaceAssetState,
    IdentityStatus,
    PermittedUse,
)
from likeness_protection.error_handler import domain_exception_handler
from likeness_protection.errors import (
    DuplicateIdentityError,
    IdentityNotFoundError,
    LikenessProtectionError,
)
from likeness_protection.router import router
from likeness_protection.schemas import (
    BiometricConsentResponse,
    ConsentResponse,
    EmbeddingResponse,
    FaceAssetResponse,
    IdentityListResponse,
    IdentityResponse,
    PresignedUrlResponse,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

_NOW = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
_OWNER = "dev-owner-000000000000"   # matches dev stub
_ID = "6660000000000000000000aa"


def _consent_resp() -> ConsentResponse:
    return ConsentResponse(
        status="active",
        version=1,
        permitted_uses=[PermittedUse.NEWS_REPORTING],
        biometric_processing=BiometricConsentResponse(
            granted=True,
            notice_version="v1.0",
            granted_at=_NOW,
        ),
        updated_at=_NOW,
    )


def _identity_resp(status: str = "active") -> IdentityResponse:
    return IdentityResponse(
        id=_ID,
        display_name="Alice",
        status=IdentityStatus(status),
        created_at=_NOW,
        updated_at=_NOW,
        face_asset=FaceAssetResponse(
            content_type="image/jpeg",
            size_bytes=1024,
            width=400,
            height=400,
            state=FaceAssetState.STORED,
        ),
        embedding=EmbeddingResponse(state=EmbeddingState.NOT_GENERATED),
        protection_ready=False,
        consent=_consent_resp(),
    )


def _make_app(identity_svc: MagicMock, consent_svc: MagicMock) -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(LikenessProtectionError, domain_exception_handler)  # type: ignore[arg-type]
    app.include_router(router)
    app.dependency_overrides[get_identity_service] = lambda: identity_svc
    app.dependency_overrides[get_consent_service] = lambda: consent_svc
    return app


def _jpeg_bytes() -> bytes:
    from PIL import Image
    img = Image.new("RGB", (400, 400), color=(10, 20, 30))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


# ── POST /identities ──────────────────────────────────────────────────────────


class TestRegisterEndpoint:
    def test_201_on_new_registration(self):
        identity_svc = MagicMock()
        identity_svc.register = AsyncMock(return_value=(_identity_resp(), False))
        app = _make_app(identity_svc, MagicMock())

        with TestClient(app) as client:
            resp = client.post(
                "/identities",
                data={
                    "display_name": "Alice",
                    "biometric_consent": "true",
                    "consent_notice_version": "v1.0",
                },
                files={"face_image": ("face.jpg", _jpeg_bytes(), "image/jpeg")},
            )

        assert resp.status_code == 201
        assert resp.json()["id"] == _ID
        assert "Location" in resp.headers

    def test_200_on_replay(self):
        identity_svc = MagicMock()
        identity_svc.register = AsyncMock(return_value=(_identity_resp(), True))
        app = _make_app(identity_svc, MagicMock())

        with TestClient(app) as client:
            resp = client.post(
                "/identities",
                data={
                    "display_name": "Alice",
                    "biometric_consent": "true",
                    "consent_notice_version": "v1.0",
                },
                files={"face_image": ("face.jpg", _jpeg_bytes(), "image/jpeg")},
            )

        assert resp.status_code == 200
        assert resp.headers.get("Idempotent-Replay") == "true"

    def test_409_on_duplicate(self):
        identity_svc = MagicMock()
        identity_svc.register = AsyncMock(
            side_effect=DuplicateIdentityError(existing_identity_id=_ID)
        )
        app = _make_app(identity_svc, MagicMock())

        with TestClient(app) as client:
            resp = client.post(
                "/identities",
                data={
                    "display_name": "Bob",
                    "biometric_consent": "true",
                    "consent_notice_version": "v1.0",
                },
                files={"face_image": ("face.jpg", _jpeg_bytes(), "image/jpeg")},
            )

        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "duplicate_identity"


# ── GET /identities ───────────────────────────────────────────────────────────


class TestListEndpoint:
    def test_list_returns_items(self):
        identity_svc = MagicMock()
        identity_svc.list_for_owner = AsyncMock(
            return_value=IdentityListResponse(items=[_identity_resp()], next_after=None)
        )
        app = _make_app(identity_svc, MagicMock())

        with TestClient(app) as client:
            resp = client.get("/identities")

        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1

    def test_list_passes_pagination_params(self):
        identity_svc = MagicMock()
        identity_svc.list_for_owner = AsyncMock(
            return_value=IdentityListResponse(items=[], next_after=None)
        )
        app = _make_app(identity_svc, MagicMock())

        with TestClient(app) as client:
            client.get("/identities?limit=5&after=someid&include_withdrawn=true")

        call_kwargs = identity_svc.list_for_owner.call_args.kwargs
        assert call_kwargs["limit"] == 5
        assert call_kwargs["after"] == "someid"
        assert call_kwargs["include_withdrawn"] is True


# ── GET /identities/{id} ──────────────────────────────────────────────────────


class TestGetEndpoint:
    def test_get_active_identity(self):
        identity_svc = MagicMock()
        identity_svc.get = AsyncMock(return_value=_identity_resp())
        app = _make_app(identity_svc, MagicMock())

        with TestClient(app) as client:
            resp = client.get(f"/identities/{_ID}")

        assert resp.status_code == 200
        assert resp.json()["id"] == _ID

    def test_404_on_not_found(self):
        identity_svc = MagicMock()
        identity_svc.get = AsyncMock(side_effect=IdentityNotFoundError(_ID))
        app = _make_app(identity_svc, MagicMock())

        with TestClient(app) as client:
            resp = client.get(f"/identities/{_ID}")

        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "identity_not_found"


# ── GET /identities/{id}/face-image-url ──────────────────────────────────────


class TestFaceImageUrlEndpoint:
    def test_returns_presigned_url(self):
        identity_svc = MagicMock()
        identity_svc.get_face_image_url = AsyncMock(
            return_value=PresignedUrlResponse(
                url="https://minio.example.com/signed",
                expires_at=_NOW,
            )
        )
        app = _make_app(identity_svc, MagicMock())

        with TestClient(app) as client:
            resp = client.get(f"/identities/{_ID}/face-image-url")

        assert resp.status_code == 200
        assert resp.json()["url"].startswith("https://")


# ── GET /identities/{id}/consent ─────────────────────────────────────────────


class TestGetConsentEndpoint:
    def test_returns_consent(self):
        consent_svc = MagicMock()
        consent_svc.get_consent = AsyncMock(return_value=_consent_resp())
        app = _make_app(MagicMock(), consent_svc)

        with TestClient(app) as client:
            resp = client.get(f"/identities/{_ID}/consent")

        assert resp.status_code == 200
        assert resp.json()["version"] == 1


# ── PUT /identities/{id}/consent ─────────────────────────────────────────────


class TestUpdateConsentEndpoint:
    def test_update_returns_new_consent(self):
        consent_svc = MagicMock()
        updated = _consent_resp()
        consent_svc.update_consent = AsyncMock(return_value=updated)
        app = _make_app(MagicMock(), consent_svc)

        with TestClient(app) as client:
            resp = client.put(
                f"/identities/{_ID}/consent",
                json={"permitted_uses": ["educational"], "expected_version": 1},
            )

        assert resp.status_code == 200

    def test_409_on_version_conflict(self):
        from likeness_protection.errors import VersionConflictError

        consent_svc = MagicMock()
        consent_svc.update_consent = AsyncMock(
            side_effect=VersionConflictError(current_version=3)
        )
        app = _make_app(MagicMock(), consent_svc)

        with TestClient(app) as client:
            resp = client.put(
                f"/identities/{_ID}/consent",
                json={"permitted_uses": [], "expected_version": 1},
            )

        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "version_conflict"


# ── POST /identities/{id}/consent/revoke ─────────────────────────────────────


class TestRevokeConsentEndpoint:
    def test_revoke_returns_withdrawn_identity(self):
        consent_svc = MagicMock()
        consent_svc.revoke_consent = AsyncMock(
            return_value=_identity_resp("withdrawn")
        )
        app = _make_app(MagicMock(), consent_svc)

        with TestClient(app) as client:
            resp = client.post(
                f"/identities/{_ID}/consent/revoke",
                json={"reason": "no longer needed"},
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "withdrawn"

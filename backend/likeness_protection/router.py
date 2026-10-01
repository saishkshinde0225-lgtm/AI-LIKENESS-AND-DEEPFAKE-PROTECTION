"""
FastAPI router for the Identity + Consent domain.

Endpoints
---------
POST   /identities                         Register a new protected identity
GET    /identities                         List caller's identities (paginated)
GET    /identities/{id}                    Get one identity (tombstone if withdrawn)
GET    /identities/{id}/face-image-url     Presigned GET for the face asset
GET    /identities/{id}/consent            Get current consent
PUT    /identities/{id}/consent            Replace permitted_uses (optimistic lock)
POST   /identities/{id}/consent/revoke     Withdraw identity + revoke all consent

Responsibilities
----------------
- HTTP only: parse request, call service, map result to response, set headers.
- Auth dependency yields owner_id; router passes it to service.
- Multipart parsing for the image upload happens here.
- The router never imports repository or storage types.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Query, Response, UploadFile, status

from likeness_protection.deps import (
    ConsentServiceDep,
    IdentityServiceDep,
    OwnerIdDep,
)
from likeness_protection.domain.enums import PermittedUse
from likeness_protection.schemas import (
    ConsentResponse,
    ConsentRevokeRequest,
    ConsentUpdateRequest,
    IdentityListResponse,
    IdentityResponse,
    PresignedUrlResponse,
)

router = APIRouter(prefix="/identities", tags=["identities"])

_MAX_IMAGE_BYTES = 10 * 1024 * 1024   # 10 MB stream read cap


# ── POST /identities ──────────────────────────────────────────────────────────


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=IdentityResponse,
    summary="Register a protected identity",
)
async def register_identity(
    owner_id: OwnerIdDep,
    identity_service: IdentityServiceDep,
    response: Response,
    # Multipart form fields
    display_name: Annotated[str, Form()],
    biometric_consent: Annotated[bool, Form()],
    consent_notice_version: Annotated[str, Form()],
    face_image: UploadFile,
    permitted_uses: Annotated[list[PermittedUse], Form()] = None,  # type: ignore[assignment]
) -> IdentityResponse:
    """Register a new protected identity with a face image upload.

    Returns 201 on creation.  An exact-match replay of an existing identity
    returns 200 with `Idempotent-Replay: true`.
    """
    from likeness_protection.schemas import IdentityRegisterForm

    if permitted_uses is None:
        permitted_uses = []
    form = IdentityRegisterForm(
        display_name=display_name,
        biometric_consent=biometric_consent,
        consent_notice_version=consent_notice_version,
        permitted_uses=permitted_uses,
    )

    # Read the upload stream with a hard cap (enforced before any decode).
    raw_bytes = await face_image.read(_MAX_IMAGE_BYTES + 1)

    identity_response, is_replay = await identity_service.register(
        owner_id=owner_id,
        form=form,
        raw_image=raw_bytes,
    )

    if is_replay:
        response.status_code = status.HTTP_200_OK
        response.headers["Idempotent-Replay"] = "true"
    else:
        response.headers["Location"] = f"/identities/{identity_response.id}"

    return identity_response


# ── GET /identities ───────────────────────────────────────────────────────────


@router.get(
    "",
    response_model=IdentityListResponse,
    summary="List caller's protected identities",
)
async def list_identities(
    owner_id: OwnerIdDep,
    identity_service: IdentityServiceDep,
    include_withdrawn: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    after: Annotated[str | None, Query()] = None,
) -> IdentityListResponse:
    return await identity_service.list_for_owner(
        owner_id=owner_id,
        include_withdrawn=include_withdrawn,
        limit=limit,
        after=after,
    )


# ── GET /identities/{id} ──────────────────────────────────────────────────────


@router.get(
    "/{identity_id}",
    response_model=IdentityResponse,
    summary="Get a protected identity",
)
async def get_identity(
    identity_id: str,
    owner_id: OwnerIdDep,
    identity_service: IdentityServiceDep,
) -> IdentityResponse:
    """Returns the identity, including the tombstone if it is withdrawn."""
    return await identity_service.get(
        identity_id=identity_id,
        owner_id=owner_id,
        include_withdrawn=True,
    )


# ── GET /identities/{id}/face-image-url ──────────────────────────────────────


@router.get(
    "/{identity_id}/face-image-url",
    response_model=PresignedUrlResponse,
    summary="Get a presigned URL for the face image",
)
async def get_face_image_url(
    identity_id: str,
    owner_id: OwnerIdDep,
    identity_service: IdentityServiceDep,
) -> PresignedUrlResponse:
    """Returns a short-lived presigned GET URL.  409 if identity is withdrawn."""
    return await identity_service.get_face_image_url(
        identity_id=identity_id,
        owner_id=owner_id,
    )


# ── GET /identities/{id}/consent ─────────────────────────────────────────────


@router.get(
    "/{identity_id}/consent",
    response_model=ConsentResponse,
    summary="Get current consent for an identity",
)
async def get_consent(
    identity_id: str,
    owner_id: OwnerIdDep,
    consent_service: ConsentServiceDep,
) -> ConsentResponse:
    return await consent_service.get_consent(
        identity_id=identity_id,
        owner_id=owner_id,
    )


# ── PUT /identities/{id}/consent ─────────────────────────────────────────────


@router.put(
    "/{identity_id}/consent",
    response_model=ConsentResponse,
    summary="Update permitted uses (optimistic lock)",
)
async def update_consent(
    identity_id: str,
    owner_id: OwnerIdDep,
    consent_service: ConsentServiceDep,
    body: ConsentUpdateRequest,
) -> ConsentResponse:
    """Replace the permitted_uses list.

    `expected_version` must match the current consent version.
    If the incoming uses are identical to current, returns 200 without
    bumping the version (safe retry after client timeout).
    """
    return await consent_service.update_consent(
        identity_id=identity_id,
        owner_id=owner_id,
        request=body,
    )


# ── POST /identities/{id}/consent/revoke ─────────────────────────────────────


@router.post(
    "/{identity_id}/consent/revoke",
    response_model=IdentityResponse,
    summary="Revoke consent and withdraw the identity",
)
async def revoke_consent(
    identity_id: str,
    owner_id: OwnerIdDep,
    consent_service: ConsentServiceDep,
    body: ConsentRevokeRequest,
) -> IdentityResponse:
    """Withdraw the identity and revoke all consent.  Idempotent."""
    return await consent_service.revoke_consent(
        identity_id=identity_id,
        owner_id=owner_id,
        request=body,
    )

"""
Pydantic request and response schemas.

These define the API contract.  They are deliberately separate from the
MongoDB document models (domain/documents.py) so that storage shape and
API shape can evolve independently.

Key conventions
---------------
- All datetimes are UTC-aware and serialise as ISO-8601 with "Z" suffix.
- Enum fields use their string values (model_config uses use_enum_values).
- Response models never expose MinIO bucket names or object keys.
- `protection_ready` is always computed, never stored:
      status == active
      AND embedding.state == ready
      AND consent.status == active
  It is always False in this sprint (no embeddings yet).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)

from likeness_protection.domain.enums import (
    EmbeddingState,
    FaceAssetState,
    IdentityStatus,
    PermittedUse,
)

# ── Shared config ─────────────────────────────────────────────────────────────

_MODEL_CFG = ConfigDict(
    use_enum_values=True,
    populate_by_name=True,
    str_strip_whitespace=True,
)

DisplayName = Annotated[str, StringConstraints(min_length=1, max_length=100)]


# ── Request schemas ───────────────────────────────────────────────────────────


class IdentityRegisterForm(BaseModel):
    """Form fields for POST /identities (multipart).

    The face_image UploadFile is handled separately by the router and is
    NOT part of this schema.
    """

    model_config = _MODEL_CFG

    display_name: DisplayName
    biometric_consent: bool
    consent_notice_version: str = Field(
        ...,
        min_length=1,
        description="Version string of the consent notice shown to the user.",
    )
    permitted_uses: list[PermittedUse] = Field(
        default_factory=list,
        description="Third-party uses the owner permits. Empty = no use allowed.",
    )

    @field_validator("biometric_consent")
    @classmethod
    def consent_must_be_true(cls, v: bool) -> bool:
        if not v:
            raise ValueError(
                "biometric_consent must be true to register an identity."
            )
        return v

    @field_validator("permitted_uses", mode="before")
    @classmethod
    def deduplicate_uses(cls, v: list[object]) -> list[object]:
        # Preserve order while deduplicating.
        seen: set[object] = set()
        return [x for x in v if not (x in seen or seen.add(x))]  # type: ignore[func-returns-value]


class ConsentUpdateRequest(BaseModel):
    """Body for PUT /identities/{id}/consent."""

    model_config = _MODEL_CFG

    permitted_uses: list[PermittedUse]
    expected_version: int = Field(
        ...,
        ge=1,
        description="Current consent version. Optimistic lock guard.",
    )

    @field_validator("permitted_uses", mode="before")
    @classmethod
    def deduplicate_uses(cls, v: list[object]) -> list[object]:
        seen: set[object] = set()
        return [x for x in v if not (x in seen or seen.add(x))]  # type: ignore[func-returns-value]


class ConsentRevokeRequest(BaseModel):
    """Body for POST /identities/{id}/consent/revoke."""

    model_config = _MODEL_CFG

    reason: Annotated[str, StringConstraints(max_length=500)] | None = None


# ── Response sub-schemas ──────────────────────────────────────────────────────


class BiometricConsentResponse(BaseModel):
    """Nested under ConsentResponse — the biometric-processing consent block."""

    model_config = _MODEL_CFG

    granted: bool
    notice_version: str
    granted_at: datetime


class ConsentResponse(BaseModel):
    """Returned by GET/PUT /identities/{id}/consent and embedded in IdentityResponse."""

    model_config = _MODEL_CFG

    status: str            # "active" | "revoked"
    version: int
    permitted_uses: list[PermittedUse]
    biometric_processing: BiometricConsentResponse
    updated_at: datetime
    revoked_at: datetime | None = None


class FaceAssetResponse(BaseModel):
    """Safe face asset metadata — no bucket name or object key exposed."""

    model_config = _MODEL_CFG

    content_type: str
    size_bytes: int
    width: int
    height: int
    state: FaceAssetState


class EmbeddingResponse(BaseModel):
    model_config = _MODEL_CFG

    state: EmbeddingState


class IdentityResponse(BaseModel):
    """Full identity representation, including embedded consent snapshot."""

    model_config = _MODEL_CFG

    id: str
    display_name: str
    status: IdentityStatus
    created_at: datetime
    updated_at: datetime
    withdrawn_at: datetime | None = None
    face_asset: FaceAssetResponse
    embedding: EmbeddingResponse
    protection_ready: bool        # always False this sprint
    consent: ConsentResponse


class PresignedUrlResponse(BaseModel):
    """Response for GET /identities/{id}/face-image-url."""

    model_config = _MODEL_CFG

    url: str
    expires_at: datetime


class IdentityListResponse(BaseModel):
    """Paginated list of identities."""

    model_config = _MODEL_CFG

    items: list[IdentityResponse]
    next_after: str | None = None   # opaque cursor (identity id)


# ── Error envelope ────────────────────────────────────────────────────────────


class ErrorDetail(BaseModel):
    model_config = _MODEL_CFG

    code: str
    message: str
    details: dict[str, object] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    model_config = _MODEL_CFG

    error: ErrorDetail

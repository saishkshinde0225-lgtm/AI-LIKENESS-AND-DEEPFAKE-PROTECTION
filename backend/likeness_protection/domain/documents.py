"""
MongoDB document models for the Identity + Consent system.

These are internal data transfer objects — the shape of documents as
they come out of MongoDB.  They are NOT the API-facing Pydantic models
(those live in schemas.py).

Design notes
------------
- All ObjectIds are exposed as plain strings (str, not bson.ObjectId) so
  nothing above the repository layer needs to import bson.
- Timestamps are always UTC-aware datetimes.
- Optional fields that may be cleared (e.g. object_key after purge) use
  `| None` rather than a sentinel string like "".
- `schema_version` enables future migrations without collection scans.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from likeness_protection.domain.enums import (
    EmbeddingState,
    FaceAssetState,
    IdentityStatus,
    PermittedUse,
)

# ── Sub-documents ─────────────────────────────────────────────────────────────


@dataclass(slots=True)
class FaceAssetDoc:
    """Embedded sub-document: metadata for the stored face image.

    object_key and sha256 are cleared (set to None) after the object is
    purged so that the tombstone contains no biometric references.
    """

    bucket: str
    content_type: str          # always "image/jpeg" (canonical form)
    size_bytes: int
    width: int
    height: int
    uploaded_at: datetime
    state: FaceAssetState

    object_key: str | None = None   # cleared on purge
    sha256: str | None = None       # cleared on purge; dedupe key while active


@dataclass(slots=True)
class EmbeddingDoc:
    """Embedded sub-document: ML embedding state (future sprint)."""

    state: EmbeddingState = EmbeddingState.NOT_GENERATED
    model: str | None = None
    model_version: str | None = None
    generated_at: datetime | None = None
    failure_reason: str | None = None


@dataclass(slots=True)
class ConsentHistoryEntry:
    """One entry in the append-only history array on ConsentPolicyDoc.

    Records the *previous* permitted_uses before each update, so the
    full audit trail is inside the document.
    """

    version: int
    permitted_uses: list[PermittedUse]
    changed_at: datetime


# ── Top-level documents ───────────────────────────────────────────────────────


@dataclass(slots=True)
class ProtectedIdentityDoc:
    """Mirrors the `protected_identities` collection document.

    _id is stored as bson.ObjectId in Mongo; the repository layer
    converts it to a hex string before constructing this dataclass.
    """

    id: str                        # hex string of ObjectId
    owner_id: str
    display_name: str
    status: IdentityStatus
    face_asset: FaceAssetDoc
    embedding: EmbeddingDoc
    created_at: datetime
    updated_at: datetime
    schema_version: int = 1

    withdrawn_at: datetime | None = None


@dataclass(slots=True)
class ConsentPolicyDoc:
    """Mirrors the `consent_policies` collection document.

    One document per identity (unique index on identity_id).
    owner_id is denormalised so consent queries can be owner-scoped
    without a join.
    """

    id: str
    identity_id: str
    owner_id: str

    # Biometric processing consent — required to register; never demoted.
    biometric_granted: bool
    biometric_notice_version: str
    biometric_granted_at: datetime

    # Third-party permitted uses.  Empty list == no third-party use allowed.
    permitted_uses: list[PermittedUse]

    status: str           # "active" | "revoked"  (IdentityStatus reused semantically)
    version: int          # starts at 1; bumped on each permitted_uses change

    history: list[ConsentHistoryEntry]   # prior versions, append-only

    created_at: datetime
    updated_at: datetime
    schema_version: int = 1

    revoked_at: datetime | None = None
    revoke_reason: str | None = None

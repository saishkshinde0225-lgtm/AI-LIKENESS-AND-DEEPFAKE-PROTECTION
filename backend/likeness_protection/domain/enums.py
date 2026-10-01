"""
Domain enums for the Identity + Consent system.

All enum values are the canonical strings stored in MongoDB and
returned in API responses.  Adding a new PermittedUse is additive
and backward-compatible.
"""

from __future__ import annotations

from enum import StrEnum


class PermittedUse(StrEnum):
    """Third-party uses that an identity owner may allow.

    An empty list on a ConsentPolicy means *nothing* is permitted
    (not that the list is unset).  Detection and takedown read this.
    """

    SATIRE_PARODY = "satire_parody"
    NEWS_REPORTING = "news_reporting"
    EDUCATIONAL = "educational"
    LICENSED_COMMERCIAL = "licensed_commercial"


class IdentityStatus(StrEnum):
    """Lifecycle status of a ProtectedIdentity.

    Transitions are one-way: active → withdrawn.
    Withdrawal is terminal; re-protecting requires a new registration.
    """

    ACTIVE = "active"
    WITHDRAWN = "withdrawn"


class FaceAssetState(StrEnum):
    """Tracks whether the binary face asset still exists in object storage.

    stored       – object is in MinIO; presigned URLs may be issued.
    purge_pending – withdrawal committed; deletion not yet confirmed.
    purged       – object deleted; object_key and sha256 cleared from doc.
    """

    STORED = "stored"
    PURGE_PENDING = "purge_pending"
    PURGED = "purged"


class EmbeddingState(StrEnum):
    """Lifecycle of the ArcFace embedding (ML step, not this sprint).

    not_generated – default; identity is valid but not yet matchable.
    pending       – job dispatched to embedding pipeline.
    ready         – embedding stored; identity is fully protected.
    failed        – pipeline error; may be retried (→ pending).

    This is intentionally decoupled from IdentityStatus so that
    "active identity, no embedding yet" is a normal, non-error state.
    """

    NOT_GENERATED = "not_generated"
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"

"""
Domain exception hierarchy for the Identity + Consent system.

Rules:
- Every domain error is a subclass of LikenessProtectionError.
- HTTP status codes and error codes live here as class attributes so
  the FastAPI exception handler is a dumb mapper with no logic.
- Services raise these; routers/handlers never catch and re-raise raw
  pymongo or minio exceptions — those are translated in repository/storage.

Error envelope shape (serialised by the handler):
    {
      "error": {
        "code":    "snake_case_code",
        "message": "human-readable sentence",
        "details": { ... }   # optional, depends on the exception
      }
    }
"""

from __future__ import annotations

from typing import Any


class LikenessProtectionError(Exception):
    """Base class.  All domain exceptions inherit from this."""

    http_status: int = 500
    code: str = "internal_error"

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


# ── 4xx client errors ────────────────────────────────────────────────────────


class ConsentRequiredError(LikenessProtectionError):
    """biometric_consent was false or consent fields were absent."""

    http_status = 422
    code = "consent_required"

    def __init__(self, message: str = "Biometric processing consent is required to register an identity.") -> None:
        super().__init__(message)


class ValidationError(LikenessProtectionError):
    """A form field failed Pydantic validation (re-raised as domain error)."""

    http_status = 422
    code = "validation_error"


class InvalidImageError(LikenessProtectionError):
    """The uploaded file is not a valid, supported image.

    details.reason explains why: wrong_format | animated | too_small |
    decompression_bomb | corrupt | unreadable.
    """

    http_status = 422
    code = "invalid_image"

    def __init__(self, reason: str, message: str | None = None) -> None:
        super().__init__(
            message or f"Image rejected: {reason}.",
            details={"reason": reason},
        )


class FileTooLargeError(LikenessProtectionError):
    """Upload exceeded the configured byte limit."""

    http_status = 413
    code = "file_too_large"

    def __init__(self, limit_bytes: int) -> None:
        super().__init__(
            f"File exceeds the maximum allowed size of {limit_bytes // (1024 * 1024)} MB.",
            details={"limit_bytes": limit_bytes},
        )


class UnsupportedMediaTypeError(LikenessProtectionError):
    """Content-type or magic bytes do not match an allowed image format."""

    http_status = 415
    code = "unsupported_media_type"

    def __init__(self, declared_type: str | None = None) -> None:
        super().__init__(
            "Only JPEG, PNG, and WebP images are accepted.",
            details={"declared_type": declared_type} if declared_type else {},
        )


class DuplicateIdentityError(LikenessProtectionError):
    """An active identity with the same canonical image already exists.

    details.existing_identity_id lets the client locate the duplicate.
    When all registration fields match it is a replay (→ 200), not a 409.
    The repository layer resolves which case applies before raising this.
    """

    http_status = 409
    code = "duplicate_identity"

    def __init__(self, existing_identity_id: str) -> None:
        super().__init__(
            "An active protected identity already exists for this image.",
            details={"existing_identity_id": existing_identity_id},
        )


class VersionConflictError(LikenessProtectionError):
    """expected_version did not match the current consent document version."""

    http_status = 409
    code = "version_conflict"

    def __init__(self, current_version: int) -> None:
        super().__init__(
            "Consent document has been updated since you last fetched it.",
            details={"current_version": current_version},
        )


class IdentityWithdrawnError(LikenessProtectionError):
    """A mutating operation was attempted on a withdrawn identity."""

    http_status = 409
    code = "identity_withdrawn"

    def __init__(self, identity_id: str) -> None:
        super().__init__(
            "This identity has been withdrawn and can no longer be modified.",
            details={"identity_id": identity_id},
        )


class IdentityNotFoundError(LikenessProtectionError):
    """Identity does not exist or does not belong to the requesting owner.

    We always return 404, never 403, to avoid leaking existence to
    non-owners.
    """

    http_status = 404
    code = "identity_not_found"

    def __init__(self, identity_id: str) -> None:
        super().__init__(
            "Identity not found.",
            details={"identity_id": identity_id},
        )


# ── 5xx infrastructure errors ────────────────────────────────────────────────


class StorageUnavailableError(LikenessProtectionError):
    """MinIO was unreachable or returned an unexpected error."""

    http_status = 503
    code = "storage_unavailable"

    def __init__(self, message: str = "Object storage is temporarily unavailable.") -> None:
        super().__init__(message)


class ConsentInconsistentError(LikenessProtectionError):
    """An active identity has no consent document (data corruption).

    We fail closed: return 500 and log loudly.  Never guess or default.
    """

    http_status = 500
    code = "consent_inconsistent"

    def __init__(self, identity_id: str) -> None:
        super().__init__(
            "Identity consent record is missing or inconsistent. "
            "This is a data integrity error; please contact support.",
            details={"identity_id": identity_id},
        )

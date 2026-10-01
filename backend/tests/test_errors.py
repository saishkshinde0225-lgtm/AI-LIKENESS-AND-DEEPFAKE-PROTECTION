"""Tests for errors.py — domain exception types and their attributes."""

from __future__ import annotations

from likeness_protection.errors import (
    ConsentInconsistentError,
    ConsentRequiredError,
    DuplicateIdentityError,
    FileTooLargeError,
    IdentityNotFoundError,
    IdentityWithdrawnError,
    InvalidImageError,
    LikenessProtectionError,
    StorageUnavailableError,
    UnsupportedMediaTypeError,
    VersionConflictError,
)


class TestExceptionHierarchy:
    def test_all_are_base_subclasses(self):
        exceptions = [
            ConsentRequiredError(),
            InvalidImageError("corrupt"),
            FileTooLargeError(10 * 1024 * 1024),
            UnsupportedMediaTypeError(),
            DuplicateIdentityError("abc123"),
            VersionConflictError(3),
            IdentityWithdrawnError("id1"),
            IdentityNotFoundError("id2"),
            StorageUnavailableError(),
            ConsentInconsistentError("id3"),
        ]
        for exc in exceptions:
            assert isinstance(exc, LikenessProtectionError), type(exc)

    def test_http_status_codes(self):
        assert ConsentRequiredError().http_status == 422
        assert InvalidImageError("x").http_status == 422
        assert FileTooLargeError(1).http_status == 413
        assert UnsupportedMediaTypeError().http_status == 415
        assert DuplicateIdentityError("x").http_status == 409
        assert VersionConflictError(1).http_status == 409
        assert IdentityWithdrawnError("x").http_status == 409
        assert IdentityNotFoundError("x").http_status == 404
        assert StorageUnavailableError().http_status == 503
        assert ConsentInconsistentError("x").http_status == 500

    def test_error_codes(self):
        assert DuplicateIdentityError("x").code == "duplicate_identity"
        assert VersionConflictError(1).code == "version_conflict"
        assert IdentityNotFoundError("x").code == "identity_not_found"
        assert ConsentInconsistentError("x").code == "consent_inconsistent"

    def test_details_populated(self):
        exc = DuplicateIdentityError("abc123")
        assert exc.details["existing_identity_id"] == "abc123"

        exc2 = VersionConflictError(5)
        assert exc2.details["current_version"] == 5

        exc3 = InvalidImageError("too_small")
        assert exc3.details["reason"] == "too_small"

        exc4 = FileTooLargeError(1024)
        assert exc4.details["limit_bytes"] == 1024

    def test_identity_not_found_never_403(self):
        # Existence leakage prevention: always 404.
        exc = IdentityNotFoundError("secret_id")
        assert exc.http_status == 404
        assert exc.code == "identity_not_found"

    def test_consent_inconsistent_fails_closed(self):
        exc = ConsentInconsistentError("id_xyz")
        assert exc.http_status == 500
        assert "id_xyz" in exc.details["identity_id"]

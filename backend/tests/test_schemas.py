"""Tests for schemas.py — request/response Pydantic models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from likeness_protection.domain.enums import PermittedUse
from likeness_protection.schemas import (
    ConsentRevokeRequest,
    ConsentUpdateRequest,
    IdentityRegisterForm,
)


class TestIdentityRegisterForm:
    def test_valid_form_parses(self):
        form = IdentityRegisterForm(
            display_name="Alice",
            biometric_consent=True,
            consent_notice_version="v1.0",
            permitted_uses=[PermittedUse.NEWS_REPORTING],
        )
        assert form.display_name == "Alice"
        assert form.biometric_consent is True

    def test_biometric_consent_false_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            IdentityRegisterForm(
                display_name="Bob",
                biometric_consent=False,
                consent_notice_version="v1.0",
            )
        errors = exc_info.value.errors()
        assert any("biometric_consent" in str(e) for e in errors)

    def test_empty_display_name_raises(self):
        with pytest.raises(ValidationError):
            IdentityRegisterForm(
                display_name="",
                biometric_consent=True,
                consent_notice_version="v1.0",
            )

    def test_display_name_too_long_raises(self):
        with pytest.raises(ValidationError):
            IdentityRegisterForm(
                display_name="x" * 101,
                biometric_consent=True,
                consent_notice_version="v1.0",
            )

    def test_duplicate_permitted_uses_deduplicated(self):
        form = IdentityRegisterForm(
            display_name="Carol",
            biometric_consent=True,
            consent_notice_version="v1.0",
            permitted_uses=[
                PermittedUse.EDUCATIONAL,
                PermittedUse.EDUCATIONAL,
                PermittedUse.SATIRE_PARODY,
            ],
        )
        assert len(form.permitted_uses) == 2

    def test_empty_permitted_uses_is_valid(self):
        form = IdentityRegisterForm(
            display_name="Dave",
            biometric_consent=True,
            consent_notice_version="v1.0",
            permitted_uses=[],
        )
        assert form.permitted_uses == []

    def test_display_name_stripped(self):
        form = IdentityRegisterForm(
            display_name="  Alice  ",
            biometric_consent=True,
            consent_notice_version="v1.0",
        )
        assert form.display_name == "Alice"

    def test_missing_consent_notice_version_raises(self):
        with pytest.raises(ValidationError):
            IdentityRegisterForm(
                display_name="Eve",
                biometric_consent=True,
                consent_notice_version="",  # empty string should fail min_length
            )


class TestConsentUpdateRequest:
    def test_valid_update_parses(self):
        req = ConsentUpdateRequest(
            permitted_uses=[PermittedUse.SATIRE_PARODY],
            expected_version=2,
        )
        assert req.expected_version == 2

    def test_version_must_be_positive(self):
        with pytest.raises(ValidationError):
            ConsentUpdateRequest(permitted_uses=[], expected_version=0)

    def test_deduplication_of_uses(self):
        req = ConsentUpdateRequest(
            permitted_uses=[PermittedUse.EDUCATIONAL, PermittedUse.EDUCATIONAL],
            expected_version=1,
        )
        assert len(req.permitted_uses) == 1


class TestConsentRevokeRequest:
    def test_optional_reason(self):
        req = ConsentRevokeRequest()
        assert req.reason is None

    def test_reason_accepted(self):
        req = ConsentRevokeRequest(reason="No longer want likeness protected.")
        assert req.reason is not None

    def test_reason_too_long_raises(self):
        with pytest.raises(ValidationError):
            ConsentRevokeRequest(reason="x" * 501)

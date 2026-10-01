"""Tests for domain/enums.py."""

from __future__ import annotations

from likeness_protection.domain.enums import (
    EmbeddingState,
    FaceAssetState,
    IdentityStatus,
    PermittedUse,
)


class TestPermittedUse:
    def test_all_values_are_strings(self):
        for v in PermittedUse:
            assert isinstance(v.value, str)

    def test_round_trip_from_string(self):
        assert PermittedUse("satire_parody") == PermittedUse.SATIRE_PARODY
        assert PermittedUse("news_reporting") == PermittedUse.NEWS_REPORTING


class TestIdentityStatus:
    def test_only_two_states(self):
        assert set(IdentityStatus) == {IdentityStatus.ACTIVE, IdentityStatus.WITHDRAWN}

    def test_values(self):
        assert IdentityStatus.ACTIVE.value == "active"
        assert IdentityStatus.WITHDRAWN.value == "withdrawn"


class TestFaceAssetState:
    def test_three_states(self):
        assert len(FaceAssetState) == 3

    def test_purge_sequence(self):
        # Nominal lifecycle ordering as strings.
        states = [s.value for s in FaceAssetState]
        assert "stored" in states
        assert "purge_pending" in states
        assert "purged" in states


class TestEmbeddingState:
    def test_four_states(self):
        assert len(EmbeddingState) == 4

    def test_default_state(self):
        assert EmbeddingState.NOT_GENERATED.value == "not_generated"

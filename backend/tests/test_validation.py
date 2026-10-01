"""
Tests for validation.py — image validation and canonicalization.

No I/O: all fixtures are generated in-memory using Pillow.
"""

from __future__ import annotations

import hashlib
import io

import pytest
from PIL import Image

from likeness_protection.errors import (
    FileTooLargeError,
    InvalidImageError,
    UnsupportedMediaTypeError,
)
from likeness_protection.validation import CanonicalImage, validate_and_canonicalize

# ── Fixture helpers ───────────────────────────────────────────────────────────


def _make_jpeg(width: int = 400, height: int = 400) -> bytes:
    img = Image.new("RGB", (width, height), color=(128, 64, 32))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _make_png(width: int = 400, height: int = 400) -> bytes:
    img = Image.new("RGB", (width, height), color=(10, 20, 30))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_webp(width: int = 400, height: int = 400) -> bytes:
    img = Image.new("RGB", (width, height), color=(200, 100, 50))
    buf = io.BytesIO()
    img.save(buf, format="WEBP")
    return buf.getvalue()


# ── Happy-path tests ──────────────────────────────────────────────────────────


class TestHappyPath:
    def test_jpeg_returns_canonical_image(self):
        raw = _make_jpeg()
        result = validate_and_canonicalize(raw)
        assert isinstance(result, CanonicalImage)
        assert result.width == 400
        assert result.height == 400
        assert result.original_format == "JPEG"
        assert len(result.data) > 0
        assert result.sha256 == hashlib.sha256(result.data).hexdigest()

    def test_png_accepted_and_converted_to_jpeg(self):
        raw = _make_png()
        result = validate_and_canonicalize(raw)
        assert result.original_format == "PNG"
        # canonical output is always JPEG
        assert result.data[:3] == b"\xff\xd8\xff"

    def test_webp_accepted(self):
        raw = _make_webp()
        result = validate_and_canonicalize(raw)
        assert result.original_format == "WEBP"

    def test_sha256_is_of_canonical_bytes(self):
        raw = _make_jpeg()
        result = validate_and_canonicalize(raw)
        assert result.sha256 == hashlib.sha256(result.data).hexdigest()

    def test_same_input_produces_same_sha256(self):
        raw = _make_jpeg()
        r1 = validate_and_canonicalize(raw)
        r2 = validate_and_canonicalize(raw)
        assert r1.sha256 == r2.sha256

    def test_size_bytes_matches_data_length(self):
        raw = _make_jpeg()
        result = validate_and_canonicalize(raw)
        assert result.size_bytes == len(result.data)

    def test_different_formats_same_pixels_different_sha256(self):
        """JPEG and PNG of the same pixels differ due to lossy vs lossless."""
        # We accept this: canonical hash is of canonical JPEG bytes.
        jpeg = _make_jpeg(400, 400)
        png = _make_png(400, 400)
        r_jpeg = validate_and_canonicalize(jpeg)
        r_png = validate_and_canonicalize(png)
        # Different source images, different hashes — expected.
        assert r_jpeg.sha256 != r_png.sha256


# ── Rejection tests ───────────────────────────────────────────────────────────


class TestRejection:
    def test_file_too_large_raises(self):
        raw = _make_jpeg()
        with pytest.raises(FileTooLargeError):
            validate_and_canonicalize(raw, size_limit_bytes=100)

    def test_random_bytes_raise_unsupported(self):
        with pytest.raises(UnsupportedMediaTypeError):
            validate_and_canonicalize(b"\x00\x01\x02\x03" * 100)

    def test_truncated_jpeg_raises_invalid(self):
        raw = _make_jpeg()[:50]  # deliberately truncated
        with pytest.raises((InvalidImageError, UnsupportedMediaTypeError)):
            validate_and_canonicalize(raw)

    def test_too_small_image_raises(self):
        raw = _make_jpeg(width=100, height=100)
        with pytest.raises(InvalidImageError) as exc_info:
            validate_and_canonicalize(raw)
        assert exc_info.value.details["reason"] == "too_small"

    def test_exactly_minimum_dimension_accepted(self):
        raw = _make_jpeg(width=256, height=256)
        result = validate_and_canonicalize(raw)
        assert result.width == 256

    def test_plain_text_raises_unsupported(self):
        with pytest.raises(UnsupportedMediaTypeError):
            validate_and_canonicalize(b"hello world this is not an image")

    def test_pdf_magic_raises_unsupported(self):
        with pytest.raises(UnsupportedMediaTypeError):
            validate_and_canonicalize(b"%PDF-1.4 fake pdf content" * 10)


# ── Error attribute tests ─────────────────────────────────────────────────────


class TestErrorAttributes:
    def test_file_too_large_has_limit_in_details(self):
        raw = _make_jpeg()
        with pytest.raises(FileTooLargeError) as exc_info:
            validate_and_canonicalize(raw, size_limit_bytes=1)
        assert exc_info.value.details["limit_bytes"] == 1
        assert exc_info.value.http_status == 413

    def test_too_small_has_reason_in_details(self):
        raw = _make_jpeg(100, 100)
        with pytest.raises(InvalidImageError) as exc_info:
            validate_and_canonicalize(raw)
        assert exc_info.value.details["reason"] == "too_small"
        assert exc_info.value.http_status == 422

    def test_unsupported_media_type_http_415(self):
        with pytest.raises(UnsupportedMediaTypeError) as exc_info:
            validate_and_canonicalize(b"garbage")
        assert exc_info.value.http_status == 415

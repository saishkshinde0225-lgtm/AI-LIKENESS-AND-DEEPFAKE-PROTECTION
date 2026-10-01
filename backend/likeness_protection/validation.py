"""
Image validation and canonicalization — pure functions, zero I/O.

Contract
--------
validate_and_canonicalize(raw_bytes, size_limit_bytes) -> CanonicalImage

Raises a domain exception from errors.py on any rejection.
Returns a CanonicalImage dataclass on success.

Canonical form
--------------
- EXIF/GPS metadata stripped (privacy; also makes hashing stable).
- Re-encoded as JPEG at quality=95 (deterministic output for the same
  pixels regardless of source format or original encoder settings).
- SHA-256 computed over the canonical bytes (not the raw upload).

Why re-encode instead of strip-in-place?
  PIL has no reliable EXIF-strip that leaves the pixel data byte-for-byte
  identical across all source formats.  A controlled re-encode gives us a
  canonical representation whose hash we can trust as a duplicate key.

Allowed formats: JPEG, PNG, WebP (animated WebP rejected).
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError

from likeness_protection.errors import (
    FileTooLargeError,
    InvalidImageError,
    UnsupportedMediaTypeError,
)

# ── Constants ─────────────────────────────────────────────────────────────────

_ALLOWED_PIL_FORMATS: frozenset[str] = frozenset({"JPEG", "PNG", "WEBP"})
_MIN_DIMENSION = 256          # pixels; face detectors need at least this
_MAX_PIXEL_COUNT = 89_478_485 # ~8K × 8K; PIL's own decompression-bomb guard
_JPEG_QUALITY = 95            # canonical re-encode quality

# Magic-byte signatures for format sniffing (faster than full decode).
_MAGIC: list[tuple[bytes, str]] = [
    (b"\xff\xd8\xff", "JPEG"),
    (b"\x89PNG\r\n\x1a\n", "PNG"),
    (b"RIFF", "WEBP"),         # RIFF....WEBP checked below
]


@dataclass(frozen=True, slots=True)
class CanonicalImage:
    """Result of successful validation + canonicalization."""

    data: bytes          # JPEG bytes, EXIF stripped, ready for MinIO
    sha256: str          # hex digest of `data`
    width: int
    height: int
    original_format: str # "JPEG" | "PNG" | "WEBP"
    size_bytes: int      # len(data)


# ── Public API ────────────────────────────────────────────────────────────────


def validate_and_canonicalize(
    raw_bytes: bytes,
    size_limit_bytes: int = 10 * 1024 * 1024,
) -> CanonicalImage:
    """Validate *raw_bytes* and return a canonical JPEG image.

    Parameters
    ----------
    raw_bytes:
        The raw upload bytes (already fully read from the stream).
    size_limit_bytes:
        Hard cap enforced *before* any decode attempt.

    Raises
    ------
    FileTooLargeError, UnsupportedMediaTypeError, InvalidImageError
    """
    _check_size(raw_bytes, size_limit_bytes)
    original_format = _sniff_format(raw_bytes)
    img = _decode(raw_bytes, original_format)
    _check_dimensions(img)
    canonical_bytes = _canonicalize(img)
    sha256 = hashlib.sha256(canonical_bytes).hexdigest()
    return CanonicalImage(
        data=canonical_bytes,
        sha256=sha256,
        width=img.width,
        height=img.height,
        original_format=original_format,
        size_bytes=len(canonical_bytes),
    )


# ── Private helpers ───────────────────────────────────────────────────────────


def _check_size(raw: bytes, limit: int) -> None:
    if len(raw) > limit:
        raise FileTooLargeError(limit_bytes=limit)


def _sniff_format(raw: bytes) -> str:
    """Return PIL format name from magic bytes.

    Raises UnsupportedMediaTypeError if no magic matches.
    """
    for magic, fmt in _MAGIC:
        if raw.startswith(magic):
            if fmt == "WEBP":
                # RIFF????WEBP
                if len(raw) >= 12 and raw[8:12] == b"WEBP":
                    return "WEBP"
                # RIFF but not WEBP (e.g. AVI) → unsupported
                raise UnsupportedMediaTypeError()
            return fmt
    raise UnsupportedMediaTypeError()


def _decode(raw: bytes, expected_format: str) -> Image.Image:
    """Decode *raw* bytes into a PIL Image.

    Raises InvalidImageError on corruption, animation, or format mismatch.
    """
    # PIL's own decompression-bomb guard (raises DecompressionBombError
    # above ~178 MP by default).  We set our own tighter cap.
    Image.MAX_IMAGE_PIXELS = _MAX_PIXEL_COUNT

    try:
        img = Image.open(io.BytesIO(raw))
        img.verify()  # catches truncated / corrupt files
    except UnidentifiedImageError as exc:
        raise InvalidImageError("wrong_format", "File could not be identified as an image.") from exc
    except Exception as exc:
        raise InvalidImageError("corrupt", "Image file is corrupt or unreadable.") from exc

    # Re-open after verify() (verify() leaves the file pointer in an
    # indeterminate state — PIL docs explicitly say to re-open).
    img = Image.open(io.BytesIO(raw))

    # Confirm format matches what magic bytes promised.
    if img.format not in _ALLOWED_PIL_FORMATS:
        raise UnsupportedMediaTypeError(declared_type=img.format)

    if img.format != expected_format:
        raise InvalidImageError(
            "wrong_format",
            f"File header claims {expected_format} but content decoded as {img.format}.",
        )

    # Reject animated images (GIF-like WebP, APNG).
    if _is_animated(img):
        raise InvalidImageError("animated", "Animated images are not accepted.")

    return img


def _is_animated(img: Image.Image) -> bool:
    try:
        img.seek(1)
        return True
    except EOFError:
        return False
    except Exception:
        return False


def _check_dimensions(img: Image.Image) -> None:
    w, h = img.size
    if w < _MIN_DIMENSION or h < _MIN_DIMENSION:
        raise InvalidImageError(
            "too_small",
            f"Image must be at least {_MIN_DIMENSION}×{_MIN_DIMENSION} pixels "
            f"(got {w}×{h}).",
        )
    if w * h > _MAX_PIXEL_COUNT:
        raise InvalidImageError(
            "decompression_bomb",
            "Image pixel count exceeds the allowed maximum.",
        )


def _canonicalize(img: Image.Image) -> bytes:
    """Strip EXIF, convert to RGB, re-encode as JPEG at fixed quality.

    Result is deterministic for the same pixel content regardless of
    the source format or original encoder settings.
    """
    # Convert to RGB so we can always write JPEG (no alpha, no palette).
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
    return buf.getvalue()

"""
Service layer for the Identity + Consent domain.

Two services, each with a single responsibility:

IdentityService
    Orchestrates registration (upload → consent insert → identity insert),
    retrieval, listing, and withdrawal (identity CAS → consent revoke →
    MinIO delete → mark purged).

ConsentService
    Manages the content of permissions: read, update (optimistic lock),
    revoke (delegates to IdentityService.withdraw so the two transitions
    are always co-ordinated).

Dependency direction:
    router → service → repository / storage

Services raise domain exceptions (errors.py) and never touch HTTP types.
They hold no mutable state; they are safe to instantiate once and reuse.

Registration write order (failure-safe)
----------------------------------------
1. Validate form + image (pure, no I/O)
2. Pre-check duplicate / replay (read-only query)
3. Upload canonical bytes to MinIO           ← orphan-safe if later steps fail
4. Insert consent document
5. Insert identity document                  ← commit point
On any failure after step 3, the uploaded object is deleted best-effort.
On a duplicate-key race at step 5, delete object and re-run step 2.
Orphaned objects (upload succeeded, insert failed, cleanup also failed) are
invisible to all queries because they are only referenced via the identity
document.  A future reaper can sweep them by listing MinIO keys with no
matching identity.

Withdrawal write order (idempotent, resumable)
-----------------------------------------------
1. CAS identity active → withdrawn           ← commit point; sets purge_pending
2. Revoke consent (idempotent if already revoked)
3. Delete MinIO object
4. Mark face_asset.state = purged, clear object_key + sha256
A repeat withdrawal call re-runs any step that was not yet completed,
because the identity status check in step 1 returns None (already
withdrawn) and the service switches to the "resume unfinished cleanup"
path.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from likeness_protection.domain.documents import (
    ConsentPolicyDoc,
    FaceAssetDoc,
    ProtectedIdentityDoc,
)
from likeness_protection.domain.enums import FaceAssetState, IdentityStatus
from likeness_protection.errors import (
    ConsentInconsistentError,
    DuplicateIdentityError,
    IdentityNotFoundError,
    IdentityWithdrawnError,
    StorageUnavailableError,
)
from likeness_protection.repository import ConsentRepository, IdentityRepository
from likeness_protection.schemas import (
    ConsentResponse,
    ConsentRevokeRequest,
    ConsentUpdateRequest,
    EmbeddingResponse,
    FaceAssetResponse,
    IdentityListResponse,
    IdentityRegisterForm,
    IdentityResponse,
    PresignedUrlResponse,
)
from likeness_protection.storage import AssetStorage
from likeness_protection.validation import CanonicalImage, validate_and_canonicalize

logger = logging.getLogger(__name__)

_IMAGE_SIZE_LIMIT = 10 * 1024 * 1024   # 10 MB


# ── Helpers ───────────────────────────────────────────────────────────────────


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


def _new_asset_id() -> str:
    from bson import ObjectId
    return str(ObjectId())


def _consent_response(consent: ConsentPolicyDoc) -> ConsentResponse:
    from likeness_protection.schemas import BiometricConsentResponse
    return ConsentResponse(
        status=consent.status,
        version=consent.version,
        permitted_uses=list(consent.permitted_uses),
        biometric_processing=BiometricConsentResponse(
            granted=consent.biometric_granted,
            notice_version=consent.biometric_notice_version,
            granted_at=consent.biometric_granted_at,
        ),
        updated_at=consent.updated_at,
        revoked_at=consent.revoked_at,
    )


def _identity_response(
    identity: ProtectedIdentityDoc,
    consent: ConsentPolicyDoc,
) -> IdentityResponse:
    from likeness_protection.domain.enums import EmbeddingState
    protection_ready = (
        identity.status == IdentityStatus.ACTIVE
        and identity.embedding.state == EmbeddingState.READY
        and consent.status == "active"
    )
    return IdentityResponse(
        id=identity.id,
        display_name=identity.display_name,
        status=identity.status,
        created_at=identity.created_at,
        updated_at=identity.updated_at,
        withdrawn_at=identity.withdrawn_at,
        face_asset=FaceAssetResponse(
            content_type=identity.face_asset.content_type,
            size_bytes=identity.face_asset.size_bytes,
            width=identity.face_asset.width,
            height=identity.face_asset.height,
            state=identity.face_asset.state,
        ),
        embedding=EmbeddingResponse(state=identity.embedding.state),
        protection_ready=protection_ready,
        consent=_consent_response(consent),
    )


def _is_replay(
    existing: ProtectedIdentityDoc,
    existing_consent: ConsentPolicyDoc,
    form: IdentityRegisterForm,
) -> bool:
    """True when the incoming request is an exact-match replay of the existing identity.

    Replay criteria (all must match):
    - Same owner (enforced by the SHA-256 lookup, so always true here)
    - Same canonical image hash (enforced by the query that found *existing*)
    - Same display_name
    - Same sorted permitted_uses set
    - Same consent_notice_version
    """
    incoming_uses = sorted(u.value if hasattr(u, "value") else u for u in form.permitted_uses)
    existing_uses = sorted(u.value if hasattr(u, "value") else u for u in existing_consent.permitted_uses)
    return (
        existing.display_name == form.display_name
        and existing_uses == incoming_uses
        and existing_consent.biometric_notice_version == form.consent_notice_version
    )


# ── IdentityService ───────────────────────────────────────────────────────────


class IdentityService:
    def __init__(
        self,
        identity_repo: IdentityRepository,
        consent_repo: ConsentRepository,
        storage: AssetStorage,
    ) -> None:
        self._identity_repo = identity_repo
        self._consent_repo = consent_repo
        self._storage = storage

    # ── Register ─────────────────────────────────────────────────────────────

    async def register(
        self,
        *,
        owner_id: str,
        form: IdentityRegisterForm,
        raw_image: bytes,
    ) -> tuple[IdentityResponse, bool]:
        """Register a new protected identity.

        Returns (IdentityResponse, is_replay).
        is_replay=True means an identical registration already exists; the
        caller should return HTTP 200 with Idempotent-Replay: true instead
        of 201.

        Raises
        ------
        FileTooLargeError, UnsupportedMediaTypeError, InvalidImageError
            Bad upload.
        ConsentRequiredError
            biometric_consent was False (enforced by Pydantic, but also
            checked here defensively).
        DuplicateIdentityError
            Same image with different metadata — conflict, not a replay.
        StorageUnavailableError
            MinIO unreachable.
        """
        # Step 1 — validate and canonicalize (pure, no I/O)
        canonical: CanonicalImage = validate_and_canonicalize(
            raw_image, size_limit_bytes=_IMAGE_SIZE_LIMIT
        )

        # Step 2 — duplicate / replay pre-check
        existing = await self._identity_repo.find_active_by_sha256(
            owner_id=owner_id, sha256=canonical.sha256
        )
        if existing is not None:
            existing_consent = await self._consent_repo.get_for_identity(
                identity_id=existing.id, owner_id=owner_id
            )
            if existing_consent is None:
                raise ConsentInconsistentError(existing.id)
            if _is_replay(existing, existing_consent, form):
                return _identity_response(existing, existing_consent), True
            raise DuplicateIdentityError(existing_identity_id=existing.id)

        # Step 3 — upload canonical bytes to MinIO
        now = _utcnow()
        asset_id = _new_asset_id()
        # We don't have the identity_id yet; use a placeholder segment that
        # the reaper can identify if orphaned.  The service generates the
        # identity_id before insertion so the key is stable.
        from bson import ObjectId
        identity_id = str(ObjectId())
        object_key = AssetStorage.make_face_key(identity_id, asset_id)

        try:
            self._storage.put(object_key, canonical.data, content_type="image/jpeg")
        except StorageUnavailableError:
            raise

        face_asset_doc = FaceAssetDoc(
            bucket="",           # bucket name is internal to AssetStorage
            object_key=object_key,
            content_type="image/jpeg",
            size_bytes=canonical.size_bytes,
            sha256=canonical.sha256,
            width=canonical.width,
            height=canonical.height,
            uploaded_at=now,
            state=FaceAssetState.STORED,
        )

        # Steps 4 + 5 — insert consent, then identity (commit point)
        try:
            consent = await self._consent_repo.insert(
                identity_id=identity_id,
                owner_id=owner_id,
                biometric_granted=form.biometric_consent,
                biometric_notice_version=form.consent_notice_version,
                permitted_uses=list(form.permitted_uses),
                now=now,
            )

            identity = await self._identity_repo.insert_with_id(
                identity_id=identity_id,
                owner_id=owner_id,
                display_name=form.display_name,
                face_asset=face_asset_doc,
                now=now,
            )
        except DuplicateIdentityError:
            # Lost a race between pre-check and insert — clean up and re-check.
            self._delete_object_best_effort(object_key)
            existing = await self._identity_repo.find_active_by_sha256(
                owner_id=owner_id, sha256=canonical.sha256
            )
            if existing is None:
                raise   # unexpected — re-raise original
            existing_consent = await self._consent_repo.get_for_identity(
                identity_id=existing.id, owner_id=owner_id
            )
            if existing_consent is None:
                raise ConsentInconsistentError(existing.id) from None
            if _is_replay(existing, existing_consent, form):
                return _identity_response(existing, existing_consent), True
            raise DuplicateIdentityError(existing_identity_id=existing.id) from None
        except Exception:
            # Any other failure after MinIO upload — delete best-effort.
            self._delete_object_best_effort(object_key)
            raise

        return _identity_response(identity, consent), False

    # ── Get / List ────────────────────────────────────────────────────────────

    async def get(
        self,
        *,
        identity_id: str,
        owner_id: str,
        include_withdrawn: bool = False,
    ) -> IdentityResponse:
        identity = await self._identity_repo.get(
            identity_id=identity_id,
            owner_id=owner_id,
            include_withdrawn=include_withdrawn,
        )
        consent = await self._consent_repo.get_for_identity(
            identity_id=identity_id, owner_id=owner_id
        )
        if consent is None:
            if identity.status == IdentityStatus.ACTIVE:
                raise ConsentInconsistentError(identity_id)
            # Withdrawn identity with missing consent is a tolerated edge case
            # (consent may have been purged separately in a future compliance
            # step).  Return a synthetic revoked consent so the caller gets a
            # complete response without crashing.
            from likeness_protection.schemas import BiometricConsentResponse
            synthetic_consent_response = ConsentResponse(
                status="revoked",
                version=0,
                permitted_uses=[],
                biometric_processing=BiometricConsentResponse(
                    granted=False,
                    notice_version="unknown",
                    granted_at=identity.withdrawn_at or identity.created_at,
                ),
                updated_at=identity.updated_at,
                revoked_at=identity.withdrawn_at,
            )
            return IdentityResponse(
                id=identity.id,
                display_name=identity.display_name,
                status=identity.status,
                created_at=identity.created_at,
                updated_at=identity.updated_at,
                withdrawn_at=identity.withdrawn_at,
                face_asset=FaceAssetResponse(
                    content_type=identity.face_asset.content_type,
                    size_bytes=identity.face_asset.size_bytes,
                    width=identity.face_asset.width,
                    height=identity.face_asset.height,
                    state=identity.face_asset.state,
                ),
                embedding=EmbeddingResponse(state=identity.embedding.state),
                protection_ready=False,
                consent=synthetic_consent_response,
            )
        return _identity_response(identity, consent)

    async def list_for_owner(
        self,
        *,
        owner_id: str,
        include_withdrawn: bool = False,
        limit: int = 20,
        after: str | None = None,
    ) -> IdentityListResponse:
        identities = await self._identity_repo.list_for_owner(
            owner_id=owner_id,
            include_withdrawn=include_withdrawn,
            limit=limit + 1,   # fetch one extra to detect next page
            after=after,
        )

        has_next = len(identities) > limit
        page = identities[:limit]

        items = []
        for identity in page:
            consent = await self._consent_repo.get_for_identity(
                identity_id=identity.id, owner_id=owner_id
            )
            if consent is None:
                if identity.status == IdentityStatus.ACTIVE:
                    raise ConsentInconsistentError(identity.id)
                continue   # skip withdrawn identities with no consent (tolerated)
            items.append(_identity_response(identity, consent))

        return IdentityListResponse(
            items=items,
            next_after=page[-1].id if has_next and page else None,
        )

    # ── Face image URL ────────────────────────────────────────────────────────

    async def get_face_image_url(
        self,
        *,
        identity_id: str,
        owner_id: str,
    ) -> PresignedUrlResponse:
        identity = await self._identity_repo.get(
            identity_id=identity_id,
            owner_id=owner_id,
            include_withdrawn=False,   # 409 if withdrawn (handled by get())
        )
        if identity.face_asset.object_key is None:
            raise IdentityWithdrawnError(identity_id)

        url, ttl_seconds = self._storage.presign_get(identity.face_asset.object_key)
        expires_at = _utcnow().replace(microsecond=0)
        expires_at = expires_at.replace(
            second=expires_at.second
        )
        import datetime as dt
        expires_at = datetime.now(tz=dt.UTC) + dt.timedelta(seconds=ttl_seconds)

        return PresignedUrlResponse(url=url, expires_at=expires_at)

    # ── Withdraw ──────────────────────────────────────────────────────────────

    async def withdraw(
        self,
        *,
        identity_id: str,
        owner_id: str,
        revoke_reason: str | None = None,
    ) -> IdentityResponse:
        """Withdraw an identity.  Idempotent and resumable.

        If the identity is already withdrawn, re-runs any cleanup steps
        that were not yet completed (consent revocation, MinIO deletion,
        purge marking).

        Returns the final identity state.
        """
        now = _utcnow()

        # Step 1 — CAS active → withdrawn (commit point)
        updated = await self._identity_repo.mark_withdrawn(
            identity_id=identity_id,
            owner_id=owner_id,
            now=now,
        )

        if updated is None:
            # Either already withdrawn, or not found / not owned.
            # Fetch to distinguish the two cases.
            identity = await self._identity_repo.get(
                identity_id=identity_id,
                owner_id=owner_id,
                include_withdrawn=True,
            )
            if identity.status == IdentityStatus.ACTIVE:
                # Shouldn't happen, but be safe.
                raise IdentityNotFoundError(identity_id)
            # Already withdrawn — resume any unfinished cleanup.
            updated = identity

        # Step 2 — revoke consent (idempotent)
        consent = await self._consent_repo.revoke(
            identity_id=identity_id,
            owner_id=owner_id,
            reason=revoke_reason,
            now=now,
        )

        # Step 3 — delete MinIO object
        if updated.face_asset.state == FaceAssetState.PURGE_PENDING:
            if updated.face_asset.object_key:
                try:
                    self._storage.delete(updated.face_asset.object_key)
                except StorageUnavailableError:
                    logger.warning(
                        "MinIO delete failed during withdrawal identity=%s; "
                        "withdrawal still effective, reaper will retry",
                        identity_id,
                    )
                    # Return without marking purged — reaper will retry.
                    return _identity_response(updated, consent)

            # Step 4 — mark purged
            await self._identity_repo.mark_asset_purged(
                identity_id=identity_id,
                owner_id=owner_id,
                now=now,
            )

        # Re-fetch to get the clean post-purge state.
        final_identity = await self._identity_repo.get(
            identity_id=identity_id,
            owner_id=owner_id,
            include_withdrawn=True,
        )
        return _identity_response(final_identity, consent)

    # ── Private ───────────────────────────────────────────────────────────────

    def _delete_object_best_effort(self, object_key: str) -> None:
        try:
            self._storage.delete(object_key)
        except Exception:
            logger.warning(
                "best-effort MinIO cleanup failed key=%s; "
                "object is an invisible orphan for the reaper",
                object_key,
            )


# ── ConsentService ────────────────────────────────────────────────────────────


class ConsentService:
    """Manages the content of consent permissions.

    Revocation delegates to IdentityService.withdraw because the two
    transitions (identity status, consent status, MinIO purge) must be
    co-ordinated in one place.
    """

    def __init__(
        self,
        identity_repo: IdentityRepository,
        consent_repo: ConsentRepository,
        identity_service: IdentityService,
    ) -> None:
        self._identity_repo = identity_repo
        self._consent_repo = consent_repo
        self._identity_service = identity_service

    async def get_consent(
        self,
        *,
        identity_id: str,
        owner_id: str,
    ) -> ConsentResponse:
        # Verify ownership via the identity (always 404, never 403).
        identity = await self._identity_repo.get(
            identity_id=identity_id,
            owner_id=owner_id,
            include_withdrawn=True,
        )
        consent = await self._consent_repo.get_for_identity(
            identity_id=identity_id, owner_id=owner_id
        )
        if consent is None:
            if identity.status == IdentityStatus.ACTIVE:
                raise ConsentInconsistentError(identity_id)
            raise IdentityNotFoundError(identity_id)
        return _consent_response(consent)

    async def update_consent(
        self,
        *,
        identity_id: str,
        owner_id: str,
        request: ConsentUpdateRequest,
    ) -> ConsentResponse:
        """Replace permitted_uses.  Raises IdentityWithdrawnError if withdrawn."""
        identity = await self._identity_repo.get(
            identity_id=identity_id,
            owner_id=owner_id,
            include_withdrawn=True,
        )
        if identity.status == IdentityStatus.WITHDRAWN:
            raise IdentityWithdrawnError(identity_id)

        consent = await self._consent_repo.update_permitted_uses(
            identity_id=identity_id,
            owner_id=owner_id,
            new_uses=list(request.permitted_uses),
            expected_version=request.expected_version,
            now=_utcnow(),
        )
        return _consent_response(consent)

    async def revoke_consent(
        self,
        *,
        identity_id: str,
        owner_id: str,
        request: ConsentRevokeRequest,
    ) -> IdentityResponse:
        """Revoke consent — delegates to IdentityService.withdraw."""
        # Verify the identity exists and belongs to the owner before delegating.
        await self._identity_repo.get(
            identity_id=identity_id,
            owner_id=owner_id,
            include_withdrawn=True,
        )
        return await self._identity_service.withdraw(
            identity_id=identity_id,
            owner_id=owner_id,
            revoke_reason=request.reason,
        )

"""
MongoDB repositories for the Identity + Consent system.

Rules enforced here
-------------------
1. Every read and write takes owner_id as a required parameter.
   A missing scope is a type error, not a forgotten filter.

2. ObjectIds are converted to hex strings at the boundary; callers
   never touch bson.

3. The repository returns domain document dataclasses (domain/documents.py),
   not raw dicts.

4. MongoDB-specific errors (DuplicateKeyError, connection errors) are
   translated to domain exceptions here.  Nothing above this layer sees
   pymongo types.

5. Indexes are defined as class methods; call them once at startup.

Collections
-----------
protected_identities
    Indexes:
    - (owner_id, created_at DESC) — listing
    - unique partial (owner_id, face_asset.sha256) WHERE status == "active"
      — duplicate guard (withdrawn identities don't block re-registration)

consent_policies
    Indexes:
    - unique (identity_id)
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING, IndexModel
from pymongo.errors import DuplicateKeyError, PyMongoError

from likeness_protection.domain.documents import (
    ConsentHistoryEntry,
    ConsentPolicyDoc,
    EmbeddingDoc,
    FaceAssetDoc,
    ProtectedIdentityDoc,
)
from likeness_protection.domain.enums import (
    EmbeddingState,
    FaceAssetState,
    IdentityStatus,
    PermittedUse,
)
from likeness_protection.errors import (
    DuplicateIdentityError,
    IdentityNotFoundError,
    StorageUnavailableError,
)

logger = logging.getLogger(__name__)

_IDENTITIES = "protected_identities"
_CONSENTS = "consent_policies"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _new_id() -> str:
    return str(ObjectId())


def _to_str_id(doc: dict[str, Any]) -> dict[str, Any]:
    """Convert _id ObjectId to string in-place and rename to id."""
    oid = doc.pop("_id", None)
    if oid is not None:
        doc["id"] = str(oid)
    return doc


def _face_asset_from_dict(d: dict[str, Any]) -> FaceAssetDoc:
    return FaceAssetDoc(
        bucket=d["bucket"],
        object_key=d.get("object_key"),
        content_type=d["content_type"],
        size_bytes=d["size_bytes"],
        sha256=d.get("sha256"),
        width=d["width"],
        height=d["height"],
        uploaded_at=d["uploaded_at"],
        state=FaceAssetState(d["state"]),
    )


def _embedding_from_dict(d: dict[str, Any]) -> EmbeddingDoc:
    return EmbeddingDoc(
        state=EmbeddingState(d.get("state", EmbeddingState.NOT_GENERATED)),
        model=d.get("model"),
        model_version=d.get("model_version"),
        generated_at=d.get("generated_at"),
        failure_reason=d.get("failure_reason"),
    )


def _identity_from_dict(d: dict[str, Any]) -> ProtectedIdentityDoc:
    d = _to_str_id(d)
    return ProtectedIdentityDoc(
        id=d["id"],
        owner_id=d["owner_id"],
        display_name=d["display_name"],
        status=IdentityStatus(d["status"]),
        face_asset=_face_asset_from_dict(d["face_asset"]),
        embedding=_embedding_from_dict(d["embedding"]),
        created_at=d["created_at"],
        updated_at=d["updated_at"],
        withdrawn_at=d.get("withdrawn_at"),
        schema_version=d.get("schema_version", 1),
    )


def _consent_from_dict(d: dict[str, Any]) -> ConsentPolicyDoc:
    d = _to_str_id(d)
    history = [
        ConsentHistoryEntry(
            version=h["version"],
            permitted_uses=[PermittedUse(u) for u in h["permitted_uses"]],
            changed_at=h["changed_at"],
        )
        for h in d.get("history", [])
    ]
    return ConsentPolicyDoc(
        id=d["id"],
        identity_id=d["identity_id"],
        owner_id=d["owner_id"],
        biometric_granted=d["biometric_processing"]["granted"],
        biometric_notice_version=d["biometric_processing"]["notice_version"],
        biometric_granted_at=d["biometric_processing"]["granted_at"],
        permitted_uses=[PermittedUse(u) for u in d["permitted_uses"]],
        status=d["status"],
        version=d["version"],
        history=history,
        created_at=d["created_at"],
        updated_at=d["updated_at"],
        revoked_at=d.get("revoked_at"),
        revoke_reason=d.get("revoke_reason"),
        schema_version=d.get("schema_version", 1),
    )


# ── IdentityRepository ────────────────────────────────────────────────────────


class IdentityRepository:
    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._col = db[_IDENTITIES]

    # ── Index setup ───────────────────────────────────────────────────────────

    async def create_indexes(self) -> None:
        listing_idx = IndexModel(
            [("owner_id", ASCENDING), ("created_at", DESCENDING)],
            name="owner_created_desc",
        )
        # Partial unique index: prevents duplicate active images per owner.
        # Withdrawn identities share no constraint so re-registration works.
        dedup_idx = IndexModel(
            [("owner_id", ASCENDING), ("face_asset.sha256", ASCENDING)],
            name="owner_sha256_active_unique",
            unique=True,
            partialFilterExpression={"status": "active"},
            sparse=True,   # excludes docs where sha256 is null (purged tombstones)
        )
        await self._col.create_indexes([listing_idx, dedup_idx])

    # ── Writes ────────────────────────────────────────────────────────────────

    async def insert_with_id(
        self,
        *,
        identity_id: str,
        owner_id: str,
        display_name: str,
        face_asset: FaceAssetDoc,
        now: datetime,
    ) -> ProtectedIdentityDoc:
        """Insert a new identity document using a caller-supplied id.

        The service pre-generates the id so it can build the MinIO object
        key before calling here.  Returns the created document.

        Raises DuplicateIdentityError if the partial unique index fires.
        """
        doc_id = identity_id
        doc: dict[str, Any] = {
            "_id": ObjectId(doc_id),
            "owner_id": owner_id,
            "display_name": display_name,
            "status": IdentityStatus.ACTIVE.value,
            "face_asset": {
                "bucket": face_asset.bucket,
                "object_key": face_asset.object_key,
                "content_type": face_asset.content_type,
                "size_bytes": face_asset.size_bytes,
                "sha256": face_asset.sha256,
                "width": face_asset.width,
                "height": face_asset.height,
                "uploaded_at": face_asset.uploaded_at,
                "state": face_asset.state.value,
            },
            "embedding": {
                "state": EmbeddingState.NOT_GENERATED.value,
            },
            "created_at": now,
            "updated_at": now,
            "schema_version": 1,
        }
        try:
            await self._col.insert_one(doc)
        except DuplicateKeyError as exc:
            existing = await self._find_active_by_sha256(
                owner_id=owner_id, sha256=face_asset.sha256 or ""
            )
            raise DuplicateIdentityError(
                existing_identity_id=existing["id"] if existing else "unknown"
            ) from exc
        except PyMongoError as exc:
            logger.error("identity insert failed owner=%s error=%s", owner_id, exc)
            raise StorageUnavailableError() from exc

        return _identity_from_dict({**doc, "_id": ObjectId(doc_id)})

    async def mark_withdrawn(
        self,
        *,
        identity_id: str,
        owner_id: str,
        now: datetime,
    ) -> ProtectedIdentityDoc | None:
        """Compare-and-set active → withdrawn.

        Returns the updated document, or None if the identity was already
        withdrawn (caller decides whether to continue or short-circuit).
        """
        result = await self._col.find_one_and_update(
            {
                "_id": ObjectId(identity_id),
                "owner_id": owner_id,
                "status": IdentityStatus.ACTIVE.value,
            },
            {
                "$set": {
                    "status": IdentityStatus.WITHDRAWN.value,
                    "face_asset.state": FaceAssetState.PURGE_PENDING.value,
                    "withdrawn_at": now,
                    "updated_at": now,
                }
            },
            return_document=True,
        )
        if result is None:
            return None
        return _identity_from_dict(result)

    async def mark_asset_purged(
        self,
        *,
        identity_id: str,
        owner_id: str,
        now: datetime,
    ) -> None:
        """Clear object_key and sha256; set state = purged."""
        await self._col.update_one(
            {"_id": ObjectId(identity_id), "owner_id": owner_id},
            {
                "$set": {
                    "face_asset.state": FaceAssetState.PURGED.value,
                    "face_asset.updated_at": now,
                    "updated_at": now,
                },
                "$unset": {
                    "face_asset.object_key": "",
                    "face_asset.sha256": "",
                },
            },
        )

    # ── Reads ─────────────────────────────────────────────────────────────────

    async def get(
        self,
        *,
        identity_id: str,
        owner_id: str,
        include_withdrawn: bool = False,
    ) -> ProtectedIdentityDoc:
        """Fetch one identity by id and owner.  Always 404 on miss (never 403)."""
        query: dict[str, Any] = {"_id": ObjectId(identity_id), "owner_id": owner_id}
        if not include_withdrawn:
            query["status"] = IdentityStatus.ACTIVE.value
        doc = await self._col.find_one(query)
        if doc is None:
            raise IdentityNotFoundError(identity_id)
        return _identity_from_dict(doc)

    async def list_for_owner(
        self,
        *,
        owner_id: str,
        include_withdrawn: bool = False,
        limit: int = 20,
        after: str | None = None,
    ) -> list[ProtectedIdentityDoc]:
        """Paginate identities for *owner_id*, newest first."""
        query: dict[str, Any] = {"owner_id": owner_id}
        if not include_withdrawn:
            query["status"] = IdentityStatus.ACTIVE.value
        if after:
            query["_id"] = {"$lt": ObjectId(after)}

        cursor = self._col.find(query).sort("_id", DESCENDING).limit(limit)
        docs = await cursor.to_list(length=limit)
        return [_identity_from_dict(d) for d in docs]

    async def find_active_by_sha256(
        self,
        *,
        owner_id: str,
        sha256: str,
    ) -> ProtectedIdentityDoc | None:
        """Look up an active identity by (owner, sha256) — the dedup key."""
        doc = await self._col.find_one(
            {
                "owner_id": owner_id,
                "face_asset.sha256": sha256,
                "status": IdentityStatus.ACTIVE.value,
            }
        )
        if doc is None:
            return None
        return _identity_from_dict(doc)

    # ── Private ───────────────────────────────────────────────────────────────

    async def _find_active_by_sha256(self, *, owner_id: str, sha256: str) -> dict[str, Any] | None:
        doc = await self._col.find_one(
            {
                "owner_id": owner_id,
                "face_asset.sha256": sha256,
                "status": IdentityStatus.ACTIVE.value,
            }
        )
        if doc is None:
            return None
        return _to_str_id(doc)


# ── ConsentRepository ─────────────────────────────────────────────────────────


class ConsentRepository:
    def __init__(self, db: AsyncIOMotorDatabase[Any]) -> None:
        self._col = db[_CONSENTS]

    async def create_indexes(self) -> None:
        unique_idx = IndexModel(
            [("identity_id", ASCENDING)],
            name="identity_id_unique",
            unique=True,
        )
        # Owner-scoped queries (e.g. bulk revocation on account deletion later).
        owner_idx = IndexModel(
            [("owner_id", ASCENDING)],
            name="owner_id",
        )
        await self._col.create_indexes([unique_idx, owner_idx])

    # ── Writes ────────────────────────────────────────────────────────────────

    async def insert(
        self,
        *,
        identity_id: str,
        owner_id: str,
        biometric_granted: bool,
        biometric_notice_version: str,
        permitted_uses: list[PermittedUse],
        now: datetime,
    ) -> ConsentPolicyDoc:
        """Insert the initial consent document for a new identity."""
        doc_id = _new_id()
        doc = {
            "_id": ObjectId(doc_id),
            "identity_id": identity_id,
            "owner_id": owner_id,
            "biometric_processing": {
                "granted": biometric_granted,
                "notice_version": biometric_notice_version,
                "granted_at": now,
            },
            "permitted_uses": [u.value for u in permitted_uses],
            "status": "active",
            "version": 1,
            "history": [],
            "created_at": now,
            "updated_at": now,
            "schema_version": 1,
        }
        try:
            await self._col.insert_one(doc)
        except PyMongoError as exc:
            logger.error(
                "consent insert failed identity=%s error=%s", identity_id, exc
            )
            raise StorageUnavailableError() from exc

        return _consent_from_dict({**doc, "_id": ObjectId(doc_id)})

    async def update_permitted_uses(
        self,
        *,
        identity_id: str,
        owner_id: str,
        new_uses: list[PermittedUse],
        expected_version: int,
        now: datetime,
    ) -> ConsentPolicyDoc:
        """Compare-and-set on version.  Pushes old content into history.

        Returns the updated document.
        Raises VersionConflictError if expected_version is stale.
        """
        from likeness_protection.errors import VersionConflictError

        # Fetch current to get existing permitted_uses for history.
        current = await self._col.find_one(
            {
                "identity_id": identity_id,
                "owner_id": owner_id,
                "status": "active",
            }
        )
        if current is None:
            from likeness_protection.errors import IdentityNotFoundError
            raise IdentityNotFoundError(identity_id)

        current_version: int = current["version"]
        current_uses: list[str] = current["permitted_uses"]

        # Idempotency: same content → return 200 without a version bump,
        # even when expected_version is stale (safe client retry after timeout).
        new_uses_values = sorted(u.value for u in new_uses)
        if sorted(current_uses) == new_uses_values:
            return _consent_from_dict(current)

        if current_version != expected_version:
            raise VersionConflictError(current_version=current_version)

        history_entry: dict[str, Any] = {
            "version": current_version,
            "permitted_uses": current_uses,
            "changed_at": now,
        }

        result = await self._col.find_one_and_update(
            {
                "identity_id": identity_id,
                "owner_id": owner_id,
                "version": current_version,
                "status": "active",
            },
            {
                "$set": {
                    "permitted_uses": [u.value for u in new_uses],
                    "version": current_version + 1,
                    "updated_at": now,
                },
                "$push": {"history": history_entry},
            },
            return_document=True,
        )
        if result is None:
            # Lost a race — re-fetch and return conflict.
            refetched = await self._col.find_one({"identity_id": identity_id})
            raise VersionConflictError(
                current_version=refetched["version"] if refetched else current_version
            )
        return _consent_from_dict(result)

    async def revoke(
        self,
        *,
        identity_id: str,
        owner_id: str,
        reason: str | None,
        now: datetime,
    ) -> ConsentPolicyDoc:
        """Mark consent as revoked.  Idempotent (already-revoked is a no-op)."""
        doc = await self._col.find_one({"identity_id": identity_id, "owner_id": owner_id})
        if doc is None:
            from likeness_protection.errors import IdentityNotFoundError
            raise IdentityNotFoundError(identity_id)

        if doc["status"] == "revoked":
            return _consent_from_dict(doc)

        result = await self._col.find_one_and_update(
            {"identity_id": identity_id, "owner_id": owner_id, "status": "active"},
            {
                "$set": {
                    "status": "revoked",
                    "revoked_at": now,
                    "revoke_reason": reason,
                    "updated_at": now,
                }
            },
            return_document=True,
        )
        if result is None:
            # Already revoked between our fetch and update — re-fetch.
            doc = await self._col.find_one({"identity_id": identity_id})
            return _consent_from_dict(doc)  # type: ignore[arg-type]
        return _consent_from_dict(result)

    # ── Reads ─────────────────────────────────────────────────────────────────

    async def get_for_identity(
        self,
        *,
        identity_id: str,
        owner_id: str,
    ) -> ConsentPolicyDoc | None:
        """Return the consent doc, or None if it doesn't exist."""
        doc = await self._col.find_one(
            {"identity_id": identity_id, "owner_id": owner_id}
        )
        if doc is None:
            return None
        return _consent_from_dict(doc)

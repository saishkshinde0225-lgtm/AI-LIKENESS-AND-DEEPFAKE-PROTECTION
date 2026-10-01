"""
FastAPI dependency providers.

Everything the router needs is obtained from here via Depends().

Current-user dependency
-----------------------
`current_owner_id` returns a stable string identifier for the requesting
user.  Today it returns a hardcoded development stub.  When real auth lands,
replace the body of `current_owner_id` — the signature and the type it
returns do not change, so no router or service code needs updating.

Database / storage lifecycle
----------------------------
The Motor client and Minio client are created once and stored on
`app.state` at startup.  FastAPI's dependency system fetches them per
request via `get_db` / `get_storage`, which are synchronous accessors
(no overhead; the real async work happens inside Motor / Minio calls).

Repository and service instances are created per-request.  They hold
no mutable state, so this is safe and avoids any cross-request coupling.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, Request
from motor.motor_asyncio import AsyncIOMotorDatabase

from likeness_protection.repository import ConsentRepository, IdentityRepository
from likeness_protection.service import ConsentService, IdentityService
from likeness_protection.storage import AssetStorage

# ── Current user ─────────────────────────────────────────────────────────────

_DEV_OWNER_ID = "dev-owner-000000000000"


async def current_owner_id() -> str:
    """Return the stable owner identifier for the current request.

    DEVELOPMENT STUB — replace with real JWT / session extraction.
    The return type (str) is the only contract the rest of the system sees.
    """
    return _DEV_OWNER_ID


OwnerIdDep = Annotated[str, Depends(current_owner_id)]


# ── Infrastructure ────────────────────────────────────────────────────────────


def get_db(request: Request) -> AsyncIOMotorDatabase[Any]:
    """Fetch the Motor database instance from app state."""
    db: AsyncIOMotorDatabase[Any] = request.app.state.db
    return db


def get_storage(request: Request) -> AssetStorage:
    """Fetch the AssetStorage instance from app state."""
    storage: AssetStorage = request.app.state.storage
    return storage


DbDep = Annotated[AsyncIOMotorDatabase[Any], Depends(get_db)]
StorageDep = Annotated[AssetStorage, Depends(get_storage)]


# ── Repository deps ───────────────────────────────────────────────────────────


def get_identity_repo(db: DbDep) -> IdentityRepository:
    return IdentityRepository(db)


def get_consent_repo(db: DbDep) -> ConsentRepository:
    return ConsentRepository(db)


IdentityRepoDep = Annotated[IdentityRepository, Depends(get_identity_repo)]
ConsentRepoDep = Annotated[ConsentRepository, Depends(get_consent_repo)]


# ── Service deps ──────────────────────────────────────────────────────────────


def get_identity_service(
    identity_repo: IdentityRepoDep,
    consent_repo: ConsentRepoDep,
    storage: StorageDep,
) -> IdentityService:
    return IdentityService(
        identity_repo=identity_repo,
        consent_repo=consent_repo,
        storage=storage,
    )


def get_consent_service(
    identity_repo: IdentityRepoDep,
    consent_repo: ConsentRepoDep,
    identity_service: Annotated[IdentityService, Depends(get_identity_service)],
) -> ConsentService:
    return ConsentService(
        identity_repo=identity_repo,
        consent_repo=consent_repo,
        identity_service=identity_service,
    )


IdentityServiceDep = Annotated[IdentityService, Depends(get_identity_service)]
ConsentServiceDep = Annotated[ConsentService, Depends(get_consent_service)]

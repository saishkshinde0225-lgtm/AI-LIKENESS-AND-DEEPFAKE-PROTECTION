"""
FastAPI application factory.

Usage
-----
    uvicorn likeness_protection.app:app --reload

Configuration is read from environment variables (see Settings below).
All defaults are suitable for local development.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from minio import Minio
from motor.motor_asyncio import AsyncIOMotorClient

from likeness_protection.error_handler import domain_exception_handler
from likeness_protection.errors import LikenessProtectionError
from likeness_protection.repository import ConsentRepository, IdentityRepository
from likeness_protection.router import router
from likeness_protection.storage import AssetStorage

logger = logging.getLogger(__name__)

# ── Settings (env-driven, dev defaults) ───────────────────────────────────────


class Settings:
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "likeness_protection"
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_secure: bool = False
    minio_bucket: str = "likeness-assets"
    presign_ttl_seconds: int = 300

    def __init__(self) -> None:
        import os
        self.mongo_uri = os.getenv("MONGO_URI", self.mongo_uri)
        self.mongo_db = os.getenv("MONGO_DB", self.mongo_db)
        self.minio_endpoint = os.getenv("MINIO_ENDPOINT", self.minio_endpoint)
        self.minio_access_key = os.getenv("MINIO_ACCESS_KEY", self.minio_access_key)
        self.minio_secret_key = os.getenv("MINIO_SECRET_KEY", self.minio_secret_key)
        self.minio_secure = os.getenv("MINIO_SECURE", "false").lower() == "true"
        self.minio_bucket = os.getenv("MINIO_BUCKET", self.minio_bucket)
        self.presign_ttl_seconds = int(os.getenv("PRESIGN_TTL_SECONDS", str(self.presign_ttl_seconds)))


# ── Lifespan ──────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    settings = Settings()

    # Motor client
    mongo_client: AsyncIOMotorClient = AsyncIOMotorClient(  # type: ignore[type-arg]
        settings.mongo_uri,
        tz_aware=True,
    )
    db = mongo_client[settings.mongo_db]
    application.state.db = db

    # Ensure indexes
    await IdentityRepository(db).create_indexes()
    await ConsentRepository(db).create_indexes()
    logger.info("MongoDB indexes ensured db=%s", settings.mongo_db)

    # MinIO client
    minio_client = Minio(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
    storage = AssetStorage(
        client=minio_client,
        bucket=settings.minio_bucket,
        presign_ttl_seconds=settings.presign_ttl_seconds,
    )
    storage.ensure_bucket_exists()
    application.state.storage = storage
    logger.info("MinIO ready bucket=%s", settings.minio_bucket)

    yield

    mongo_client.close()
    logger.info("MongoDB connection closed")


# ── Application factory ───────────────────────────────────────────────────────


def create_app() -> FastAPI:
    application = FastAPI(
        title="AI Likeness Protection & Deepfake Takedown System",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.add_exception_handler(
        LikenessProtectionError,
        domain_exception_handler,  # type: ignore[arg-type]
    )
    application.include_router(router)
    return application


app = create_app()

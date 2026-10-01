# AI Likeness Protection — Backend Foundation

FastAPI + MongoDB + MinIO backend for the Identity + Consent domain.

## Stack

| Layer | Technology |
|---|---|
| API | FastAPI 0.111+ |
| Database | MongoDB via Motor (async) |
| Object storage | MinIO |
| Validation | Pydantic v2, Pillow |
| Python | 3.11+ |

## Local setup

### Prerequisites

- Python 3.11+
- MongoDB running on `localhost:27017`
- MinIO running on `localhost:9000` (access key / secret key: `minioadmin`)

### Install

```bash
pip install -r requirements-dev.txt
```

### Run

```bash
uvicorn likeness_protection.app:app --reload
```

Interactive docs: http://localhost:8000/docs

### Configuration (environment variables)

| Variable | Default | Description |
|---|---|---|
| `MONGO_URI` | `mongodb://localhost:27017` | MongoDB connection string |
| `MONGO_DB` | `likeness_protection` | Database name |
| `MINIO_ENDPOINT` | `localhost:9000` | MinIO endpoint (no scheme) |
| `MINIO_ACCESS_KEY` | `minioadmin` | MinIO access key |
| `MINIO_SECRET_KEY` | `minioadmin` | MinIO secret key |
| `MINIO_SECURE` | `false` | Use TLS for MinIO |
| `MINIO_BUCKET` | `likeness-assets` | Private bucket name |
| `PRESIGN_TTL_SECONDS` | `300` | Face image URL lifetime |

### Test

```bash
pytest
```

### Lint / type-check

```bash
ruff check likeness_protection/
mypy likeness_protection/
```

## Module map

```
likeness_protection/
  app.py            — FastAPI factory, lifespan (index + bucket setup)
  router.py         — 7 HTTP endpoints
  service.py        — IdentityService, ConsentService (all orchestration)
  repository.py     — IdentityRepository, ConsentRepository (MongoDB)
  storage.py        — AssetStorage (MinIO wrapper)
  validation.py     — Image validation + EXIF-strip canonicalization
  schemas.py        — Pydantic request/response models
  errors.py         — Domain exception hierarchy
  error_handler.py  — FastAPI exception → error envelope
  deps.py           — Dependency injection (dev owner stub)
  domain/
    enums.py        — PermittedUse, IdentityStatus, FaceAssetState, EmbeddingState
    documents.py    — MongoDB document dataclasses

tests/
  test_enums.py
  test_errors.py
  test_schemas.py
  test_validation.py
  test_storage.py
  test_service.py
  test_router.py
```

## Authentication

`deps.py::current_owner_id()` returns a hardcoded development stub.
Replace the body of that function with real JWT / session extraction —
no other file needs changing.

## What is NOT yet implemented

- Real authentication
- ArcFace embedding pipeline (state machine is in place; plug in at the
  documented step in `IdentityService.register`)
- Detection / takedown router (reads `protection_ready=true` identities)
- Hard-delete endpoint (tombstone-only for MVP)

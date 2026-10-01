"""
FastAPI exception handler for LikenessProtectionError.

Register with:
    app.add_exception_handler(LikenessProtectionError, domain_exception_handler)

The handler is deliberately logic-free: it reads the attributes set on
the exception class and serialises them into the standard error envelope.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from likeness_protection.errors import LikenessProtectionError

logger = logging.getLogger(__name__)


async def domain_exception_handler(
    request: Request,
    exc: LikenessProtectionError,
) -> JSONResponse:
    if exc.http_status >= 500:
        logger.error(
            "domain_error code=%s path=%s",
            exc.code,
            request.url.path,
            exc_info=exc,
        )
    else:
        logger.info(
            "client_error code=%s path=%s message=%s",
            exc.code,
            request.url.path,
            exc.message,
        )

    body: dict[str, Any] = {
        "error": {
            "code": exc.code,
            "message": exc.message,
        }
    }
    if exc.details:
        body["error"]["details"] = exc.details

    return JSONResponse(status_code=exc.http_status, content=body)

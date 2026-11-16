"""Request-ID middleware for the AI service.

Attaches a correlation ID to every request/response:
- Reads X-Request-ID from incoming request (or generates a new UUID).
- Stores it on request.state.request_id for downstream use.
- Echoes it back in the X-Request-ID response header.
- Logs method, path, status code, and latency for every request.
"""
from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable

from fastapi import Request, Response

logger = logging.getLogger(__name__)


async def request_id_middleware(request: Request, call_next: Callable) -> Response:  # type: ignore[type-arg]
    """ASGI middleware: attach correlation ID and emit access log."""
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id

    start = time.monotonic()
    response: Response = await call_next(request)
    duration_ms = round((time.monotonic() - start) * 1000, 2)

    response.headers["X-Request-ID"] = request_id

    logger.info(
        "HTTP %s %s → %s",
        request.method,
        request.url.path,
        response.status_code,
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
            "service": "ai",
        },
    )
    return response

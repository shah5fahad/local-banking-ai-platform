"""Domain error types and FastAPI exception handlers for the AI service."""
from __future__ import annotations

import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from banking_common.errors import ErrorDetail, ErrorEnvelope

logger = logging.getLogger(__name__)


class AIError(Exception):
    """Typed AI domain error that maps to an HTTP response."""

    def __init__(
        self,
        error_code: str,
        message: str,
        http_status: int = 400,
        details: list[ErrorDetail] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.http_status = http_status
        self.details = details or []


class NotFoundError(AIError):
    def __init__(self, resource: str, identifier: str | None = None) -> None:
        msg = f"{resource} not found" if not identifier else f"{resource} '{identifier}' not found"
        super().__init__("NOT_FOUND", msg, http_status=404)


class ForbiddenError(AIError):
    def __init__(self, msg: str = "Access denied") -> None:
        super().__init__("FORBIDDEN", msg, http_status=403)


class UnauthorizedError(AIError):
    def __init__(self, msg: str = "Authentication required") -> None:
        super().__init__("UNAUTHORIZED", msg, http_status=401)


class ConflictError(AIError):
    def __init__(self, msg: str) -> None:
        super().__init__("CONFLICT", msg, http_status=409)


async def ai_error_handler(request: Request, exc: AIError) -> JSONResponse:
    request_id: str | None = getattr(request.state, "request_id", None)
    envelope = ErrorEnvelope(
        error_code=exc.error_code,
        message=exc.message,
        details=exc.details,
        request_id=request_id,
    )
    logger.warning(
        "AI domain error: %s",
        exc.message,
        extra={
            "request_id": request_id,
            "error_code": exc.error_code,
            "http_status": exc.http_status,
            "service": "ai",
        },
    )
    return JSONResponse(status_code=exc.http_status, content=envelope.model_dump())


async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    request_id: str | None = getattr(request.state, "request_id", None)
    details = [
        ErrorDetail(
            field=".".join(str(loc) for loc in e["loc"]),
            message=e["msg"],
            code=e["type"],
        )
        for e in exc.errors()
    ]
    envelope = ErrorEnvelope.validation_error(details=details, request_id=request_id)
    return JSONResponse(status_code=422, content=envelope.model_dump())


async def unhandled_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    request_id: str | None = getattr(request.state, "request_id", None)
    logger.exception(
        "Unhandled exception in AI service",
        extra={"request_id": request_id, "service": "ai"},
    )
    envelope = ErrorEnvelope.of(
        error_code="INTERNAL_ERROR",
        message="An unexpected error occurred. Please try again later.",
        request_id=request_id,
    )
    return JSONResponse(status_code=500, content=envelope.model_dump())

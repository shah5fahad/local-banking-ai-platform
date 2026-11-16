"""Consistent error envelope used across all services.

Every error response from Banking and AI services must serialise to this shape:

    {
        "success": false,
        "error_code": "ACCOUNT_NOT_FOUND",
        "message": "No account found for the given ID.",
        "details": [],
        "request_id": "uuid-..."
    }
"""
from __future__ import annotations

from pydantic import BaseModel


class ErrorDetail(BaseModel):
    """Optional per-field validation detail."""

    field: str | None = None
    message: str
    code: str | None = None


class ErrorEnvelope(BaseModel):
    """Top-level error response body."""

    success: bool = False
    error_code: str
    message: str
    details: list[ErrorDetail] = []
    request_id: str | None = None

    @classmethod
    def of(
        cls,
        error_code: str,
        message: str,
        request_id: str | None = None,
        details: list[ErrorDetail] | None = None,
    ) -> "ErrorEnvelope":
        """Convenience constructor."""
        return cls(
            error_code=error_code,
            message=message,
            request_id=request_id,
            details=details or [],
        )

    @classmethod
    def validation_error(
        cls,
        details: list[ErrorDetail],
        request_id: str | None = None,
    ) -> "ErrorEnvelope":
        """Convenience constructor for validation errors."""
        return cls(
            error_code="VALIDATION_ERROR",
            message="Request validation failed.",
            details=details,
            request_id=request_id,
        )

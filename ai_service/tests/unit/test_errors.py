"""Unit tests for AI error classes and FastAPI exception handlers."""
from __future__ import annotations

from unittest.mock import MagicMock
import pytest
from pydantic import BaseModel, ValidationError

from app.core.errors import (
    AIError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
    ai_error_handler,
    unhandled_exception_handler,
    validation_error_handler,
)


def test_ai_errors_status_codes() -> None:
    not_found = NotFoundError("Conversation", "c-1")
    assert not_found.http_status == 404
    assert "Conversation 'c-1' not found" in not_found.message

    forbidden = ForbiddenError()
    assert forbidden.http_status == 403

    unauth = UnauthorizedError()
    assert unauth.http_status == 401

    conflict = ConflictError("Already exists")
    assert conflict.http_status == 409


@pytest.mark.asyncio
async def test_ai_error_handler() -> None:
    req = MagicMock()
    req.state.request_id = "req-123"
    exc = NotFoundError("Document", "doc-1")

    res = await ai_error_handler(req, exc)
    assert res.status_code == 404
    import json
    body = json.loads(res.body.decode())
    assert body["error_code"] == "NOT_FOUND"
    assert body["request_id"] == "req-123"


@pytest.mark.asyncio
async def test_unhandled_exception_handler() -> None:
    req = MagicMock()
    req.state.request_id = "req-456"
    exc = RuntimeError("Database crashed")

    res = await unhandled_exception_handler(req, exc)
    assert res.status_code == 500
    import json
    body = json.loads(res.body.decode())
    assert body["error_code"] == "INTERNAL_ERROR"
    assert body["request_id"] == "req-456"

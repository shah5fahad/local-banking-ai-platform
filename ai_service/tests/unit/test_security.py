"""Unit tests for AI service JWT security and claims extraction."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from jose import jwt
import pytest

from app.core.config import AISettings
from app.core.errors import UnauthorizedError
from app.core.security import decode_banking_jwt, extract_roles, extract_session_id, extract_user_id


@pytest.fixture
def settings() -> AISettings:
    return AISettings(
        AI_DATABASE_URL="sqlite:///./test.db",
        AI_SECRET_KEY="test-secret-key-12345678901234567890",
        AI_BANKING_SERVICE_URL="http://banking:8000",
    )


def test_decode_valid_banking_jwt(settings: AISettings) -> None:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "user-uuid-1",
        "roles": ["CUSTOMER"],
        "sid": "session-1",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)

    decoded = decode_banking_jwt(token, settings)
    assert decoded["sub"] == "user-uuid-1"
    assert extract_user_id(decoded) == "user-uuid-1"
    assert extract_roles(decoded) == ["CUSTOMER"]
    assert extract_session_id(decoded) == "session-1"


def test_decode_missing_sub_raises(settings: AISettings) -> None:
    now = datetime.now(timezone.utc)
    payload = {
        "roles": ["CUSTOMER"],
        "exp": int((now + timedelta(hours=1)).timestamp()),
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)

    with pytest.raises(UnauthorizedError) as exc:
        decode_banking_jwt(token, settings)
    assert "missing subject" in exc.value.message.lower()


def test_decode_invalid_signature_raises(settings: AISettings) -> None:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "user-uuid-1",
        "exp": int((now + timedelta(hours=1)).timestamp()),
    }
    token = jwt.encode(payload, "wrong-key-secret-key-0987654321", algorithm=settings.algorithm)

    with pytest.raises(UnauthorizedError) as exc:
        decode_banking_jwt(token, settings)
    assert exc.value.http_status == 401

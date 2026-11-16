"""JWT validation for AI service. Tokens are issued by the banking service."""
from __future__ import annotations

from jose import JWTError, jwt

from app.core.config import AISettings
from app.core.errors import UnauthorizedError


def decode_banking_jwt(token: str, settings: AISettings) -> dict:
    """Decode and validate a JWT issued by the banking service.
    Returns the full payload dict.
    Raises UnauthorizedError on any validation failure.
    """
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,  # In prod: use banking service's public key
            algorithms=[settings.algorithm],
        )
        if not payload.get("sub"):
            raise UnauthorizedError("Token missing subject")
        return payload
    except JWTError as exc:
        raise UnauthorizedError(f"Invalid token: {exc}") from exc


def extract_user_id(payload: dict) -> str:
    return str(payload["sub"])


def extract_roles(payload: dict) -> list[str]:
    return payload.get("roles", [])


def extract_session_id(payload: dict) -> str | None:
    return payload.get("sid")


def create_service_token_for_user(banking_user_id: str, settings: AISettings) -> str:
    """Generate an internal short-lived JWT for system operations on behalf of a user."""
    from datetime import datetime, timedelta, timezone
    import uuid

    now = datetime.now(timezone.utc)
    payload = {
        "sub": banking_user_id,
        "roles": ["CUSTOMER"],
        "sid": f"ai-system-{uuid.uuid4()}",
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)

"""FastAPI dependency injection for the AI service."""
from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import AISettings, get_settings
from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.security import decode_banking_jwt, extract_roles, extract_user_id
from app.db.session import get_db

bearing = HTTPBearer(auto_error=False)


def get_current_token_payload(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearing),
    settings: AISettings = Depends(get_settings),
) -> dict:
    """Validate Bearer JWT and return decoded payload."""
    if not credentials:
        raise UnauthorizedError()
    return decode_banking_jwt(credentials.credentials, settings)


def get_current_user_id(payload: dict = Depends(get_current_token_payload)) -> str:
    return extract_user_id(payload)


def get_current_user_roles(payload: dict = Depends(get_current_token_payload)) -> list[str]:
    return extract_roles(payload)


def require_roles(*roles: str) -> Callable[..., None]:
    def _dep(user_roles: list[str] = Depends(get_current_user_roles)) -> None:
        if not any(r in user_roles for r in roles):
            raise ForbiddenError(f"Required role(s): {', '.join(roles)}")
    return _dep


def get_access_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearing),
) -> str:
    """Return raw JWT string for forwarding to banking service."""
    if not credentials:
        raise UnauthorizedError()
    return credentials.credentials


# Type aliases
DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[AISettings, Depends(get_settings)]
CurrentUserId = Annotated[str, Depends(get_current_user_id)]
CurrentRoles = Annotated[list[str], Depends(get_current_user_roles)]
AccessToken = Annotated[str, Depends(get_access_token)]

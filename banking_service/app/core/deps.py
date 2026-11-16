"""FastAPI dependency aliases and auth injectors for the Banking service."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Sequence

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import BankingSettings, get_settings
from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.security import decode_token
from app.db.session import get_db
from app.models.user import User

# Type aliases
DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[BankingSettings, Depends(get_settings)]

security_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security_bearer)],
    request: Request,
) -> User:
    """Extract, decode JWT and return active User object."""
    if not credentials:
        raise UnauthorizedError("Authentication required: missing Bearer token")

    payload = decode_token(credentials.credentials)
    user_id = payload.get("sub") or payload.get("user_id")
    if not user_id:
        raise UnauthorizedError("Invalid token payload: missing subject")

    stmt = select(User).where(User.id == str(user_id))
    user = db.scalar(stmt)
    if not user:
        raise UnauthorizedError("User not found")

    if not user.is_active:
        raise ForbiddenError("User account is inactive")

    if user.locked_until and user.locked_until > datetime.now(timezone.utc):
        raise ForbiddenError("User account is temporarily locked")

    # Store caller information on request state for auditing
    request.state.current_user = user
    request.state.caller_type = payload.get("caller_type", "USER")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*allowed_roles: str):
    """Dependency factory checking user has one of the required roles."""

    def role_checker(user: CurrentUser) -> User:
        user_roles = {role.name for role in user.roles}
        if not any(role in user_roles for role in allowed_roles):
            raise ForbiddenError(f"Operation requires one of roles: {', '.join(allowed_roles)}")
        return user

    return role_checker


RequireAdmin = Annotated[User, Depends(require_roles("ADMIN"))]
RequireAdminOrAuditor = Annotated[User, Depends(require_roles("ADMIN", "AUDITOR"))]


async def require_customer_only(
    user: CurrentUser,
    request: Request,
) -> User:
    """Enforce that request is made directly by customer (not automated AI service)."""
    caller_type = getattr(request.state, "caller_type", "USER")
    if caller_type == "SERVICE" or request.headers.get("X-Caller-Type") == "SERVICE":
        raise ForbiddenError("This operation can only be performed directly by the customer")
    return user


RequireCustomerOnly = Annotated[User, Depends(require_customer_only)]

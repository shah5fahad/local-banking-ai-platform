"""TokenService for issuing, rotating, and revoking tokens."""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import BankingSettings
from app.core.errors import UnauthorizedError
from app.core.security import create_access_token, hash_token
from app.models.user import User
from app.repositories.session_repository import SessionRepository
from app.repositories.user_repository import UserRepository


class TokenService:
    """Service managing access/refresh token pairs and session tracking."""

    def issue_tokens(
        self,
        user: User,
        settings: BankingSettings,
        db: Session,
        user_agent: str | None = None,
        ip: str | None = None,
    ) -> tuple[str, str, str]:
        """Issue access and refresh token pair and persist user session.

        Returns:
            (access_token, refresh_token, jti)
        """
        session_id = str(uuid.uuid4())
        jti = str(uuid.uuid4())
        raw_refresh_token = secrets.token_urlsafe(64)
        ref_hash = hash_token(raw_refresh_token)

        roles = [ur.role.name for ur in user.roles if ur.role]
        if not roles:
            # Fallback if roles not loaded or empty
            user_repo = UserRepository(db)
            roles = user_repo.get_roles(user.id) or ["CUSTOMER"]

        access_token, _ = create_access_token(
            sub=user.id,
            roles=roles,
            sid=session_id,
            settings=settings,
            jti=jti,
        )

        expires_at = datetime.now(timezone.utc) + timedelta(
            days=settings.refresh_token_expire_days
        )

        session_repo = SessionRepository(db)
        session_repo.create(
            user_id=user.id,
            refresh_token_hash=ref_hash,
            jti=jti,
            expires_at=expires_at,
            user_agent=user_agent,
            ip=ip,
            session_id=session_id,
        )

        return access_token, raw_refresh_token, jti

    def refresh(
        self,
        refresh_token: str,
        settings: BankingSettings,
        db: Session,
        user_agent: str | None = None,
        ip: str | None = None,
    ) -> tuple[str, str, str]:
        """Perform refresh token rotation.

        Revokes old session and issues new tokens. If the token was previously
        revoked, detects reuse and revokes all user sessions.
        """
        ref_hash = hash_token(refresh_token)
        session_repo = SessionRepository(db)
        sess = session_repo.get_by_refresh_hash(ref_hash)

        if not sess:
            raise UnauthorizedError("Invalid refresh token")

        if sess.revoked_at is not None:
            # Token reuse detected! Invalidate all sessions for this user.
            session_repo.revoke_all_for_user(sess.user_id)
            raise UnauthorizedError(
                "Refresh token has been revoked - potential token theft detected"
            )

        now = datetime.now(timezone.utc)
        expires_at = sess.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < now:
            session_repo.revoke(sess.id)
            raise UnauthorizedError("Refresh token has expired")

        user_repo = UserRepository(db)
        user = user_repo.get_by_id(sess.user_id)
        if not user or not user.is_active:
            raise UnauthorizedError("User account not found or disabled")

        # Revoke the consumed session
        session_repo.revoke(sess.id)

        # Issue new token pair
        return self.issue_tokens(
            user=user,
            settings=settings,
            db=db,
            user_agent=user_agent or sess.user_agent,
            ip=ip or sess.ip,
        )

    def revoke_session(self, session_id: str, db: Session) -> None:
        """Revoke a single session by ID."""
        session_repo = SessionRepository(db)
        session_repo.revoke(session_id)

    def revoke_all_sessions(
        self,
        user_id: str,
        except_session_id: str | None,
        db: Session,
    ) -> None:
        """Revoke all sessions for a user, optionally keeping the current one."""
        session_repo = SessionRepository(db)
        session_repo.revoke_all_for_user(user_id, except_session_id=except_session_id)

"""SessionRepository for UserSession / refresh token management."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.session import Session as UserSession


class SessionRepository:
    """Repository handling UserSession persistence and lifecycle."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        user_id: str,
        refresh_token_hash: str,
        jti: str,
        expires_at: datetime,
        user_agent: str | None = None,
        ip: str | None = None,
        session_id: str | None = None,
    ) -> UserSession:
        """Create and persist a new user session."""
        db_session = UserSession(
            id=session_id or str(uuid.uuid4()),
            user_id=user_id,
            refresh_token_hash=refresh_token_hash,
            jti=jti,
            expires_at=expires_at,
            user_agent=user_agent,
            ip=ip,
        )
        self.session.add(db_session)
        self.session.flush()
        return db_session

    def get_by_id(self, session_id: str) -> UserSession | None:
        """Fetch a session by its UUID."""
        return (
            self.session.query(UserSession)
            .filter(UserSession.id == session_id)
            .first()
        )

    def get_by_refresh_hash(self, hash_value: str) -> UserSession | None:
        """Fetch a session by its refresh token hash."""
        return (
            self.session.query(UserSession)
            .filter(UserSession.refresh_token_hash == hash_value)
            .first()
        )

    def get_by_jti(self, jti: str) -> UserSession | None:
        """Fetch a session by the JWT ID of the access token."""
        return (
            self.session.query(UserSession)
            .filter(UserSession.jti == jti)
            .first()
        )

    def revoke(self, session_id: str) -> None:
        """Revoke a session by ID if not already revoked."""
        db_session = self.get_by_id(session_id)
        if db_session and db_session.revoked_at is None:
            db_session.revoked_at = datetime.now(timezone.utc)
            self.session.flush()

    def revoke_all_for_user(
        self,
        user_id: str,
        except_session_id: str | None = None,
    ) -> int:
        """Revoke all active sessions for a user, optionally exempting one.

        Returns the number of sessions revoked.
        """
        query = (
            self.session.query(UserSession)
            .filter(
                UserSession.user_id == user_id,
                UserSession.revoked_at.is_(None),
            )
        )
        if except_session_id:
            query = query.filter(UserSession.id != except_session_id)

        sessions = query.all()
        now = datetime.now(timezone.utc)
        count = 0
        for s in sessions:
            s.revoked_at = now
            count += 1
        self.session.flush()
        return count

    def list_active_for_user(self, user_id: str) -> list[UserSession]:
        """Return all non-revoked, unexpired sessions for a user."""
        now = datetime.now(timezone.utc)
        return (
            self.session.query(UserSession)
            .filter(
                UserSession.user_id == user_id,
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > now,
            )
            .order_by(UserSession.created_at.desc())
            .all()
        )

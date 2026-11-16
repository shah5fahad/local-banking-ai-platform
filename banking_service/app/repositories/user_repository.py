"""Repository for User and Session aggregates."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.user import Role, Session as DbSessionModel, User
import uuid


class UserRepository:
    """Repository handling database queries for User entities."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_id(self, user_id: str) -> User | None:
        """Fetch user by ID."""
        stmt = select(User).where(User.id == user_id)
        return self.session.execute(stmt).unique().scalar_one_or_none()

    def get_by_email(self, email: str) -> User | None:
        """Fetch user by email (case-insensitive)."""
        stmt = select(User).where(User.email == email.strip().lower())
        return self.session.execute(stmt).unique().scalar_one_or_none()

    def get_by_phone(self, phone: str) -> User | None:
        """Fetch user by phone number."""
        stmt = select(User).where(User.phone == phone.strip())
        return self.session.execute(stmt).unique().scalar_one_or_none()

    def create(self, user: User) -> User:
        """Persist a new User entity."""
        self.session.add(user)
        self.session.flush()
        self.session.refresh(user)
        return user

    def update(self, user: User) -> User:
        """Update an existing User entity."""
        self.session.add(user)
        self.session.flush()
        self.session.refresh(user)
        return user

    def assign_role(self, user_id: str, role_name: str) -> None:
        """Assign a role by name to a user."""
        stmt = select(Role).where(Role.name == role_name)
        role = self.session.execute(stmt).scalar_one_or_none()
        if not role:
            role = Role(id=str(uuid.uuid4()), name=role_name)
            self.session.add(role)
            self.session.flush()

        user = self.get_by_id(user_id)
        if user and role not in user.roles:
            user.roles.append(role)
            self.session.flush()

    def get_roles(self, user_id: str) -> list[str]:
        """Fetch list of role names for a user."""
        user = self.get_by_id(user_id)
        if not user:
            return []
        return [r.name for r in user.roles]

    def revoke_other_sessions(
        self, user_id: str, current_jti: str | None = None
    ) -> int:
        """Revoke all active sessions for a user, optionally preserving current_jti."""
        now = datetime.now(timezone.utc)
        stmt = (
            update(DbSessionModel)
            .where(
                DbSessionModel.user_id == user_id,
                DbSessionModel.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        if current_jti:
            stmt = stmt.where(DbSessionModel.jti != current_jti)
        result = self.session.execute(stmt)
        self.session.flush()
        return result.rowcount

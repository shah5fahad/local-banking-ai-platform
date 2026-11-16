"""User domain service."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from app.core.errors import BankingError, ConflictError, NotFoundError
from app.core.security import hash_password, hash_pin, verify_password
from app.models.user import User
from app.repositories.account_repository import AccountRepository
from app.repositories.user_repository import UserRepository
from app.schemas.user import UpdateUserRequest

if TYPE_CHECKING:
    from app.core.config import BankingSettings


class UserService:
    """Service handling user profile, credential changes, and account summary operations."""

    @staticmethod
    def get_profile(user_id: str, db: Session) -> User:
        """Fetch user profile by user_id."""
        repo = UserRepository(db)
        user = repo.get_by_id(user_id)
        if not user:
            raise NotFoundError("User", user_id)
        return user

    @staticmethod
    def update_profile(
        user_id: str,
        data: UpdateUserRequest,
        db: Session,
        settings: BankingSettings | None = None,
    ) -> User:
        """Update user profile fields (name, phone) with duplicate phone check."""
        repo = UserRepository(db)
        user = repo.get_by_id(user_id)
        if not user:
            raise NotFoundError("User", user_id)

        if data.phone is not None and data.phone != user.phone:
            existing = repo.get_by_phone(data.phone)
            if existing and existing.id != user_id:
                raise ConflictError("Phone number is already registered to another user")
            user.phone = data.phone

        if data.full_name is not None:
            user.full_name = data.full_name

        repo.update(user)
        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def change_password(
        user_id: str,
        current_password: str,
        new_password: str,
        db: Session,
        settings: BankingSettings | None = None,
    ) -> None:
        """Verify current password, hash and store new password, and revoke other sessions."""
        repo = UserRepository(db)
        user = repo.get_by_id(user_id)
        if not user:
            raise NotFoundError("User", user_id)

        if not verify_password(current_password, user.password_hash):
            raise BankingError(
                "INVALID_CREDENTIALS",
                "Current password is incorrect",
                http_status=401,
            )

        user.password_hash = hash_password(new_password)
        repo.update(user)
        repo.revoke_other_sessions(user_id)
        db.commit()

    @staticmethod
    def set_transaction_pin(
        user_id: str,
        password: str,
        pin: str,
        db: Session,
        settings: BankingSettings | None = None,
    ) -> None:
        """Verify login password and set/update transaction PIN."""
        repo = UserRepository(db)
        user = repo.get_by_id(user_id)
        if not user:
            raise NotFoundError("User", user_id)

        if not verify_password(password, user.password_hash):
            raise BankingError(
                "INVALID_CREDENTIALS",
                "Account password verification failed",
                http_status=401,
            )

        user.transaction_pin_hash = hash_pin(pin)
        repo.update(user)
        db.commit()

    @staticmethod
    def get_summary(user_id: str, db: Session) -> dict[str, Any]:
        """Aggregate total linked accounts and combined balance."""
        user_repo = UserRepository(db)
        user = user_repo.get_by_id(user_id)
        if not user:
            raise NotFoundError("User", user_id)

        acc_repo = AccountRepository(db)
        accounts = acc_repo.list_for_user(user_id, status="ACTIVE")
        total_balance = sum(acc.balance_minor for acc in accounts)

        return {
            "user_id": user_id,
            "full_name": user.full_name,
            "total_accounts": len(accounts),
            "total_balance_minor": total_balance,
            "currency": "INR",
        }

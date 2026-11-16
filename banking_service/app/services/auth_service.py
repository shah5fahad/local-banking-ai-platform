"""AuthService for user registration, authentication, and lockout policy."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import BankingSettings
from app.core.errors import BankingError, ConflictError
from app.core.security import hash_password, verify_password
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.services.token_service import TokenService

# Password complexity regexes
_UPPERCASE_RE = re.compile(r"[A-Z]")
_LOWERCASE_RE = re.compile(r"[a-z]")
_DIGIT_RE = re.compile(r"[0-9]")
_SPECIAL_RE = re.compile(r"[^A-Za-z0-9]")


def validate_password_strength(password: str) -> None:
    """Ensure password is >= 12 chars and contains upper, lower, digit, and special char."""
    if len(password) < 12:
        raise BankingError(
            "INVALID_PASSWORD",
            "Password must be at least 12 characters long",
            http_status=422,
        )
    if not _UPPERCASE_RE.search(password):
        raise BankingError(
            "INVALID_PASSWORD",
            "Password must contain at least one uppercase letter",
            http_status=422,
        )
    if not _LOWERCASE_RE.search(password):
        raise BankingError(
            "INVALID_PASSWORD",
            "Password must contain at least one lowercase letter",
            http_status=422,
        )
    if not _DIGIT_RE.search(password):
        raise BankingError(
            "INVALID_PASSWORD",
            "Password must contain at least one digit",
            http_status=422,
        )
    if not _SPECIAL_RE.search(password):
        raise BankingError(
            "INVALID_PASSWORD",
            "Password must contain at least one special character",
            http_status=422,
        )


class AuthService:
    """Service handling user registration, authentication, and account security."""

    def __init__(self, token_service: TokenService | None = None) -> None:
        self.token_service = token_service or TokenService()

    def register(
        self,
        email: str,
        phone: str,
        full_name: str,
        password: str,
        db: Session,
        settings: BankingSettings,
        auto_create_account: bool = True,
        auto_create_card: bool = True,
        auto_create_loans: bool = True,
    ) -> User:
        """Register a new user with CUSTOMER role and auto-create primary bank account, card, and loan offers."""
        validate_password_strength(password)

        norm_email = email.strip().lower()
        norm_phone = phone.strip()

        user_repo = UserRepository(db)
        if user_repo.get_by_email(norm_email):
            raise ConflictError("An account with this email already exists")

        if user_repo.get_by_phone(norm_phone):
            raise ConflictError("An account with this phone number already exists")

        pwd_hash = hash_password(password)
        new_user = User(
            email=norm_email,
            phone=norm_phone,
            full_name=full_name.strip(),
            password_hash=pwd_hash,
        )
        user = user_repo.create(new_user)

        user_repo.assign_role(user.id, "CUSTOMER")

        if auto_create_account:
            from app.services.account_service import AccountService

            AccountService.create_initial_account(
                user_id=user.id,
                holder_name=user.full_name,
                db=db,
                settings=settings,
            )

        if auto_create_card:
            from app.services.card_service import CardService

            CardService.create_initial_card(
                user_id=user.id,
                db=db,
                settings=settings,
            )

        if auto_create_loans:
            from app.services.loan_service import LoanService

            LoanService.provision_initial_loan_offers(
                user_id=user.id,
                db=db,
                settings=settings,
            )

        db.refresh(user)
        return user

    def login(
        self,
        email: str,
        password: str,
        user_agent: str | None,
        ip: str | None,
        db: Session,
        settings: BankingSettings,
    ) -> tuple[User, str, str]:
        """Authenticate user by email and password, enforcing lockout policy.

        Returns:
            (user, access_token, refresh_token)
        """
        user_repo = UserRepository(db)
        user = user_repo.get_by_email(email.strip().lower())

        # If user does not exist, use generic error to prevent enumeration
        if not user:
            raise BankingError(
                "INVALID_CREDENTIALS",
                "Invalid email or password",
                http_status=401,
            )

        now = datetime.now(timezone.utc)

        # Check account lockout
        if user.locked_until:
            locked_until = user.locked_until
            if locked_until.tzinfo is None:
                locked_until = locked_until.replace(tzinfo=timezone.utc)
            if locked_until > now:
                remaining_sec = int((locked_until - now).total_seconds())
                raise BankingError(
                    "ACCOUNT_LOCKED",
                    f"Account is temporarily locked. Try again in {remaining_sec // 60 + 1} minutes.",
                    http_status=423,
                )
            else:
                # Lockout period expired; reset count and clear lock
                user.locked_until = None
                user.failed_login_count = 0

        # Verify password
        if not verify_password(password, user.password_hash):
            user.failed_login_count += 1
            if user.failed_login_count >= 5:
                user.locked_until = now + timedelta(minutes=30)
                user_repo.update(user)
                raise BankingError(
                    "ACCOUNT_LOCKED",
                    "Account locked due to 5 consecutive failed login attempts. Try again in 30 minutes.",
                    http_status=423,
                )
            user_repo.update(user)
            raise BankingError(
                "INVALID_CREDENTIALS",
                "Invalid email or password",
                http_status=401,
            )

        if not user.is_active:
            raise BankingError(
                "ACCOUNT_DISABLED",
                "Account has been deactivated",
                http_status=403,
            )

        # Successful authentication: reset failed count and update last_login_at
        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = now
        user_repo.update(user)

        # Issue tokens and create session
        access_token, refresh_token, _ = self.token_service.issue_tokens(
            user=user,
            settings=settings,
            db=db,
            user_agent=user_agent,
            ip=ip,
        )

        return user, access_token, refresh_token

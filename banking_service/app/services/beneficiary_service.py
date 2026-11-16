"""Beneficiary domain service with approval challenge orchestration."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.core.errors import BankingError, ConflictError, NotFoundError
from app.core.security import encrypt_field, hash_token, hmac_field, verify_pin
from app.models.approval_challenge import ApprovalChallenge
from app.models.beneficiary import Beneficiary
from app.repositories.beneficiary_repository import BeneficiaryRepository
from app.repositories.challenge_repository import ChallengeRepository
from app.repositories.user_repository import UserRepository
from app.schemas.beneficiary import CreateBeneficiaryRequest, UpdateBeneficiaryRequest

if TYPE_CHECKING:
    from app.core.config import BankingSettings


class BeneficiaryService:
    """Service handling beneficiary management and sensitive operation approval challenges."""

    @staticmethod
    def create_beneficiary(
        user_id: str,
        data: CreateBeneficiaryRequest,
        approval_token: str,
        db: Session,
        settings: BankingSettings,
    ) -> Beneficiary:
        """Validate single-use approval token, encrypt account, check uniqueness, and create beneficiary."""
        if not approval_token or not approval_token.strip():
            raise BankingError(
                "AUTHORIZATION_REQUIRED",
                "X-Approval-Token header is required to add a beneficiary",
                http_status=401,
            )

        token_hash = hash_token(approval_token.strip())
        ch_repo = ChallengeRepository(db)
        challenge = ch_repo.get_by_token_hash(token_hash)

        if not challenge:
            raise BankingError(
                "AUTHORIZATION_INVALID",
                "Invalid or expired approval token",
                http_status=401,
            )

        if challenge.user_id != user_id:
            raise BankingError(
                "AUTHORIZATION_INVALID",
                "Approval token does not belong to the authenticated user",
                http_status=401,
            )

        if challenge.status != "VERIFIED":
            raise BankingError(
                "AUTHORIZATION_INVALID",
                f"Approval token cannot be used in state '{challenge.status}'",
                http_status=401,
            )

        now = datetime.now(timezone.utc)
        exp = challenge.expires_at.replace(tzinfo=timezone.utc) if challenge.expires_at.tzinfo is None else challenge.expires_at
        if exp < now:
            challenge.status = "EXPIRED"
            db.commit()
            raise BankingError(
                "AUTHORIZATION_EXPIRED",
                "Approval token has expired",
                http_status=401,
            )

        if challenge.action != "BENEFICIARY_CREATE":
            raise BankingError(
                "AUTHORIZATION_INVALID",
                f"Token was authorized for '{challenge.action}', expected BENEFICIARY_CREATE",
                http_status=401,
            )

        secret_key = getattr(settings, "secret_key", getattr(settings, "jwt_secret", ""))
        bene_repo = BeneficiaryRepository(db)

        account_hash = hmac_field(data.account_number, secret_key)
        existing = bene_repo.get_by_hash(user_id, account_hash, data.ifsc)
        if existing and existing.status == "ACTIVE":
            raise ConflictError("Beneficiary with this account and IFSC is already saved")

        encrypted_num = encrypt_field(data.account_number, secret_key)
        last4 = data.account_number[-4:]

        beneficiary = bene_repo.create(
            user_id=user_id,
            name=data.name,
            nickname=data.nickname,
            account_number_encrypted=encrypted_num,
            last4=last4,
            account_number_hash=account_hash,
            ifsc=data.ifsc,
            bank_name=data.bank_name,
        )

        # Mark approval challenge consumed
        ch_repo.consume(challenge.id)
        db.commit()
        db.refresh(beneficiary)
        return beneficiary

    @staticmethod
    def list_beneficiaries(
        user_id: str,
        q: str | None,
        db: Session,
    ) -> list[Beneficiary]:
        """List active beneficiaries for user with optional name search."""
        repo = BeneficiaryRepository(db)
        return repo.list_for_user(user_id, q=q)

    @staticmethod
    def get_beneficiary(
        user_id: str, bene_id: str, db: Session
    ) -> Beneficiary:
        """Fetch beneficiary by ID with ownership enforcement."""
        repo = BeneficiaryRepository(db)
        b = repo.get_by_id(bene_id, user_id)
        if not b:
            raise NotFoundError("Beneficiary", bene_id)
        return b

    @staticmethod
    def update_beneficiary(
        user_id: str,
        bene_id: str,
        data: UpdateBeneficiaryRequest,
        approval_token: str,
        db: Session,
        settings: BankingSettings,
    ) -> Beneficiary:
        """Validate approval token, update beneficiary details, and reset verification status."""
        if not approval_token or not approval_token.strip():
            raise BankingError(
                "AUTHORIZATION_REQUIRED",
                "X-Approval-Token header is required to modify a beneficiary",
                http_status=401,
            )

        token_hash = hash_token(approval_token.strip())
        ch_repo = ChallengeRepository(db)
        challenge = ch_repo.get_by_token_hash(token_hash)

        if not challenge:
            raise BankingError(
                "AUTHORIZATION_INVALID",
                "Invalid or expired approval token",
                http_status=401,
            )

        if challenge.user_id != user_id or challenge.status != "VERIFIED":
            raise BankingError(
                "AUTHORIZATION_INVALID",
                "Invalid approval token",
                http_status=401,
            )

        now = datetime.now(timezone.utc)
        exp = challenge.expires_at.replace(tzinfo=timezone.utc) if challenge.expires_at.tzinfo is None else challenge.expires_at
        if exp < now:
            challenge.status = "EXPIRED"
            db.commit()
            raise BankingError(
                "AUTHORIZATION_EXPIRED",
                "Approval token has expired",
                http_status=401,
            )

        if challenge.action != "BENEFICIARY_MODIFY":
            raise BankingError(
                "AUTHORIZATION_INVALID",
                f"Token was authorized for '{challenge.action}', expected BENEFICIARY_MODIFY",
                http_status=401,
            )

        bene_repo = BeneficiaryRepository(db)
        b = bene_repo.get_by_id(bene_id, user_id)
        if not b:
            raise NotFoundError("Beneficiary", bene_id)

        if data.name is not None:
            b.name = data.name
        if data.nickname is not None:
            b.nickname = data.nickname

        # Modifying triggers re-verification per spec
        b.verification_status = "PENDING"
        bene_repo.update(b)
        ch_repo.consume(challenge.id)
        db.commit()
        db.refresh(b)
        return b

    @staticmethod
    def deactivate_beneficiary(
        user_id: str, bene_id: str, db: Session
    ) -> None:
        """Deactivate a beneficiary."""
        repo = BeneficiaryRepository(db)
        b = repo.get_by_id(bene_id, user_id)
        if not b:
            raise NotFoundError("Beneficiary", bene_id)
        repo.deactivate(bene_id, user_id)
        db.commit()

    @staticmethod
    def verify_beneficiary(
        user_id: str, bene_id: str, db: Session
    ) -> Beneficiary:
        """Mock penny-drop verification for beneficiary."""
        repo = BeneficiaryRepository(db)
        b = repo.get_by_id(bene_id, user_id)
        if not b:
            raise NotFoundError("Beneficiary", bene_id)

        b.verification_status = "VERIFIED"
        repo.update(b)
        db.commit()
        db.refresh(b)
        return b

    @staticmethod
    def create_challenge(
        user_id: str,
        action: str,
        payload_hash: str,
        db: Session,
        settings: BankingSettings,
    ) -> ApprovalChallenge:
        """Issue an approval challenge for a sensitive action."""
        user_repo = UserRepository(db)
        user = user_repo.get_by_id(user_id)
        if not user:
            raise NotFoundError("User", user_id)

        if not user.transaction_pin_hash:
            raise BankingError(
                "PIN_NOT_SET",
                "Transaction PIN is not configured. Please set your transaction PIN first.",
                http_status=400,
            )

        expiry_seconds = getattr(settings, "transfer_approval_expiry_seconds", 300)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expiry_seconds)

        ch_repo = ChallengeRepository(db)
        challenge = ch_repo.create(
            user_id=user_id,
            action=action,
            payload_hash=payload_hash,
            pin_hash=user.transaction_pin_hash,
            expires_at=expires_at,
        )
        db.commit()
        db.refresh(challenge)
        return challenge

    @staticmethod
    def verify_challenge(
        challenge_id: str,
        pin: str,
        user_id: str,
        db: Session,
        settings: BankingSettings,
    ) -> str:
        """Verify customer PIN against challenge and issue single-use approval token."""
        ch_repo = ChallengeRepository(db)
        challenge = ch_repo.get_by_id(challenge_id)
        if not challenge or challenge.user_id != user_id:
            raise NotFoundError("ApprovalChallenge", challenge_id)

        if challenge.status != "PENDING":
            raise BankingError(
                "INVALID_STATE",
                f"Challenge cannot be verified in status '{challenge.status}'",
                http_status=400,
            )

        now = datetime.now(timezone.utc)
        exp = challenge.expires_at.replace(tzinfo=timezone.utc) if challenge.expires_at.tzinfo is None else challenge.expires_at
        if exp < now:
            challenge.status = "EXPIRED"
            db.commit()
            raise BankingError(
                "CHALLENGE_EXPIRED",
                "Approval challenge has expired",
                http_status=400,
            )

        max_attempts = getattr(settings, "txn_auth_max_attempts", 5)
        if challenge.attempts >= max_attempts:
            challenge.status = "LOCKED"
            db.commit()
            raise BankingError(
                "MAX_ATTEMPTS_EXCEEDED",
                "Maximum verification attempts exceeded. Challenge is locked.",
                http_status=403,
            )

        if not challenge.pin_hash or not verify_pin(pin, challenge.pin_hash):
            challenge.attempts += 1
            if challenge.attempts >= max_attempts:
                challenge.status = "LOCKED"
            db.commit()
            raise BankingError(
                "INVALID_PIN",
                f"Incorrect transaction PIN. Attempts remaining: {max(0, max_attempts - challenge.attempts)}",
                http_status=401,
            )

        # Generate single-use approval token
        approval_token = str(uuid.uuid4())
        token_hash = hash_token(approval_token)
        ch_repo.mark_verified(challenge.id, token_hash)
        db.commit()
        return approval_token

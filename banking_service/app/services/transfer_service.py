"""TransferService implementing the transfer state machine, limits, auth challenges, and execution."""
from __future__ import annotations

import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import BankingSettings
from app.core.errors import (
    BankingError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)
from app.core.security import sha256_hash, to_utc, verify_pin
from app.models.account import BankAccount
from app.models.beneficiary import Beneficiary
from app.models.transaction import BankTransaction, TransferAuthorization
from app.models.user import User
from app.repositories.transaction_repository import TransactionRepository
from app.schemas.transfer import PrepareTransferRequest
from app.services.audit_service import AuditService
from app.services.fee_service import FeeStrategy
from app.services.limits_service import LimitsService
from app.services.transfer_state import transition


class TransferService:
    """Core domain service for orchestrating funds transfers."""

    @staticmethod
    def prepare(
        user_id: str,
        data: PrepareTransferRequest,
        idempotency_key: str,
        db: Session,
        settings: BankingSettings,
        request_id: Optional[str] = None,
        ip: Optional[str] = None,
    ) -> BankTransaction:
        """Prepare a new funds transfer, returning PENDING_APPROVAL transaction."""
        repo = TransactionRepository(db)

        # 1. Idempotency check: if key exists and not EXPIRED/CANCELLED, return existing
        if idempotency_key:
            existing = repo.get_by_idempotency_key(user_id, idempotency_key)
            if existing:
                if existing.status not in ["EXPIRED", "CANCELLED"]:
                    return existing

        # 2. Load source account (ownership check, must be ACTIVE + VERIFIED)
        account_stmt = select(BankAccount).where(
            BankAccount.id == data.source_account_id,
            BankAccount.user_id == user_id,
        )
        source_account = db.scalar(account_stmt)
        if not source_account:
            raise NotFoundError("Bank account", data.source_account_id)
        if source_account.status != "ACTIVE":
            raise ConflictError("Source bank account is not ACTIVE")
        if source_account.verification_status != "VERIFIED":
            raise ConflictError("Source bank account is not VERIFIED")

        # 3. Load beneficiary (ownership check, must be ACTIVE + VERIFIED approval_status)
        bene_stmt = select(Beneficiary).where(
            Beneficiary.id == data.beneficiary_id,
            Beneficiary.user_id == user_id,
        )
        beneficiary = db.scalar(bene_stmt)
        if not beneficiary:
            raise NotFoundError("Beneficiary", data.beneficiary_id)
        if beneficiary.status != "ACTIVE":
            raise ConflictError("Beneficiary is not ACTIVE")
        if beneficiary.approval_status != "APPROVED":
            raise BankingError(
                error_code="BENEFICIARY_NOT_APPROVED",
                message=f"Beneficiary is not APPROVED for transfers {beneficiary.approval_status}",
                http_status=422,
            )

        # 4. Compute fee via FeeStrategy
        fee_minor = FeeStrategy.calculate_fee(data.channel, data.amount_minor)
        total_debit_minor = data.amount_minor + fee_minor

        # 5. Check balance
        if source_account.balance_minor < total_debit_minor:
            raise BankingError(
                error_code="INSUFFICIENT_BALANCE",
                message="Available balance is lower than the transfer amount plus fees.",
                http_status=422,
            )

        # 6. Check limits via LimitsService
        LimitsService.check_limits(user_id, data.amount_minor, repo, settings)

        # 7. Check duplicate window: same beneficiary+amount within duplicate_window_seconds
        duplicate = repo.check_duplicate_window(
            user_id, data.beneficiary_id, data.amount_minor, settings.duplicate_window_seconds
        )
        if duplicate and duplicate.idempotency_key != idempotency_key:
            raise BankingError(
                error_code="DUPLICATE_TRANSACTION",
                message=(
                    f"A duplicate transfer to this beneficiary for {data.amount_minor} minor units "
                    f"was submitted within the last {settings.duplicate_window_seconds} seconds. "
                    f"Reference: {duplicate.reference}"
                ),
                http_status=409,
            )

        # 8. Compute unique ID, reference, and summary_hash
        txn_id = str(uuid.uuid4())
        ref_timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        reference = f"TXN{ref_timestamp}{secrets.token_hex(2).upper()}"

        summary_payload = {
            "amount_minor": data.amount_minor,
            "beneficiary_id": data.beneficiary_id,
            "currency": data.currency,
            "fee_minor": fee_minor,
            "source_account_id": data.source_account_id,
            "txn_id": txn_id,
            "user_id": user_id,
        }
        summary_hash = sha256_hash(json.dumps(summary_payload, sort_keys=True))

        # 9. Set expiry
        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=settings.transfer_approval_expiry_seconds
        )

        # 10. Persist transaction
        txn = BankTransaction(
            id=txn_id,
            reference=reference,
            user_id=user_id,
            source_account_id=data.source_account_id,
            beneficiary_id=data.beneficiary_id,
            type="TRANSFER",
            amount_minor=data.amount_minor,
            fee_minor=fee_minor,
            total_debit_minor=total_debit_minor,
            currency=data.currency,
            status="PENDING_APPROVAL",
            remark=data.remark,
            channel=data.channel,
            summary_hash=summary_hash,
            idempotency_key=idempotency_key,
            expires_at=expires_at,
        )
        db.add(txn)
        db.flush()

        # 11. Audit log
        AuditService.log(
            db=db,
            actor_user_id=user_id,
            actor_type="USER",
            action="TRANSFER_PREPARE",
            resource_type="bank_transaction",
            resource_id=txn.id,
            outcome="SUCCESS",
            request_id=request_id,
            ip=ip,
            details={
                "reference": txn.reference,
                "amount_minor": txn.amount_minor,
                "fee_minor": txn.fee_minor,
                "total_debit_minor": txn.total_debit_minor,
            },
        )
        return txn

    @staticmethod
    def create_auth_challenge(
        user_id: str,
        txn_id: str,
        db: Session,
        settings: BankingSettings,
        request_id: Optional[str] = None,
        ip: Optional[str] = None,
    ) -> TransferAuthorization:
        """Issue an authorization challenge for PENDING_APPROVAL transfer."""
        repo = TransactionRepository(db)
        txn = repo.get_by_id(txn_id, user_id=user_id)
        if not txn:
            raise NotFoundError("Transfer", txn_id)

        now = datetime.now(timezone.utc)
        txn_exp = to_utc(txn.expires_at)
        if txn_exp and txn_exp < now:
            repo.update_status(txn.id, "EXPIRED", failure_reason="Transfer approval expired")
            raise BankingError(
                error_code="AUTHORIZATION_EXPIRED",
                message="Transfer approval has expired",
                http_status=410,
            )

        if txn.status != "PENDING_APPROVAL":
            raise ConflictError(f"Cannot issue challenge for transfer with status {txn.status}")

        user = db.scalar(select(User).where(User.id == user_id))
        if not user:
            raise NotFoundError("User", user_id)

        if settings.txn_auth_method == "PIN" and not user.transaction_pin_hash:
            raise ConflictError("Transaction PIN not set. Please set PIN before authorizing transfers.")

        # Check existing authorization
        existing_auth = repo.get_authorization(txn.id)
        if existing_auth and existing_auth.status == "ISSUED":
            auth_exp = to_utc(existing_auth.expires_at)
            if auth_exp and auth_exp > now:
                return existing_auth

        challenge_secret = secrets.token_hex(16)
        challenge_hash = sha256_hash(challenge_secret)
        auth_expires_at = now + timedelta(minutes=5)

        auth = repo.create_authorization(
            transaction_id=txn.id,
            method=settings.txn_auth_method,
            challenge_hash=challenge_hash,
            summary_hash=txn.summary_hash or "",
            expires_at=auth_expires_at,
        )

        AuditService.log(
            db=db,
            actor_user_id=user_id,
            actor_type="USER",
            action="TRANSFER_CHALLENGE_CREATE",
            resource_type="transfer_authorization",
            resource_id=auth.id,
            outcome="SUCCESS",
            request_id=request_id,
            ip=ip,
            details={"transaction_id": txn.id, "method": settings.txn_auth_method},
        )
        return auth

    @staticmethod
    def authorize(
        user_id: str,
        txn_id: str,
        challenge_id: str,
        pin_or_otp: str | None,
        db: Session,
        settings: BankingSettings,
        request_id: Optional[str] = None,
        ip: Optional[str] = None,
    ) -> TransferAuthorization:
        """Verify PIN/OTP and transition transfer state to AUTHORIZED."""
        repo = TransactionRepository(db)
        txn = repo.get_by_id(txn_id, user_id=user_id)
        if not txn:
            raise NotFoundError("Transfer", txn_id)

        now = datetime.now(timezone.utc)
        txn_exp = to_utc(txn.expires_at)
        if txn_exp and txn_exp < now:
            repo.update_status(txn.id, "EXPIRED", failure_reason="Transfer expired")
            raise BankingError(
                error_code="AUTHORIZATION_EXPIRED",
                message="Transfer has expired",
                http_status=410,
            )

        if txn.status != "PENDING_APPROVAL":
            raise ConflictError(f"Transfer status is {txn.status}, cannot authorize")

        auth = repo.get_authorization_by_id(challenge_id)
        if not auth or auth.transaction_id != txn.id:
            raise NotFoundError("Transfer authorization", challenge_id)

        if auth.status == "LOCKED":
            raise BankingError(
                error_code="AUTHORIZATION_LOCKED",
                message="Transfer authorization is locked due to too many failed attempts",
                http_status=423,
            )

        if auth.status != "ISSUED":
            raise ConflictError(f"Authorization is {auth.status}, cannot verify")

        auth_exp = to_utc(auth.expires_at)
        if auth_exp and auth_exp < now:
            repo.update_authorization(auth.id, "EXPIRED")
            raise BankingError(
                error_code="AUTHORIZATION_EXPIRED",
                message="Authorization challenge has expired",
                http_status=410,
            )

        # Verify PIN
        user = db.scalar(select(User).where(User.id == user_id))
        if not user or not user.transaction_pin_hash:
            raise ConflictError("User transaction PIN is not configured")

        if not pin_or_otp or not verify_pin(pin_or_otp, user.transaction_pin_hash):
            attempts = auth.attempts + 1
            if attempts >= settings.txn_auth_max_attempts:
                repo.update_authorization(auth.id, "LOCKED", attempts=attempts)
                AuditService.log(
                    db=db,
                    actor_user_id=user_id,
                    actor_type="USER",
                    action="TRANSFER_AUTHORIZE",
                    resource_type="transfer_authorization",
                    resource_id=auth.id,
                    outcome="FAILURE",
                    request_id=request_id,
                    ip=ip,
                    details={"error": "Max attempts exceeded, locked"},
                )
                raise BankingError(
                    error_code="AUTHORIZATION_LOCKED",
                    message="Max authorization attempts exceeded. Challenge is locked.",
                    http_status=423,
                )
            repo.update_authorization(auth.id, "ISSUED", attempts=attempts)
            AuditService.log(
                db=db,
                actor_user_id=user_id,
                actor_type="USER",
                action="TRANSFER_AUTHORIZE",
                resource_type="transfer_authorization",
                resource_id=auth.id,
                outcome="FAILURE",
                request_id=request_id,
                ip=ip,
                details={"attempts": attempts, "error": "Invalid PIN"},
            )
            raise BankingError(
                error_code="AUTHORIZATION_INVALID",
                message="Invalid transaction PIN provided",
                http_status=400,
            )

        # On success: transition check & mark verified
        transition(txn.status, "AUTHORIZED", context="transfer")
        repo.update_authorization(auth.id, "VERIFIED")
        repo.update_status(txn.id, "AUTHORIZED")

        AuditService.log(
            db=db,
            actor_user_id=user_id,
            actor_type="USER",
            action="TRANSFER_AUTHORIZE",
            resource_type="bank_transaction",
            resource_id=txn.id,
            outcome="SUCCESS",
            request_id=request_id,
            ip=ip,
            details={"authorization_id": auth.id},
        )
        return auth

    @staticmethod
    def execute(
        user_id: str,
        txn_id: str,
        authorization_id: str,
        summary_hash: str,
        idempotency_key: str,
        db: Session,
        settings: BankingSettings,
        request_id: Optional[str] = None,
        ip: Optional[str] = None,
    ) -> BankTransaction:
        """Atomically deduct balance, mark COMPLETED, and consume authorization."""
        repo = TransactionRepository(db)
        txn = repo.get_by_id(txn_id, user_id=user_id)
        if not txn:
            raise NotFoundError("Transfer", txn_id)

        # Replay idempotency check
        if txn.status == "COMPLETED":
            return txn

        now = datetime.now(timezone.utc)
        txn_exp = to_utc(txn.expires_at)
        if txn_exp and txn_exp < now:
            repo.update_status(txn.id, "EXPIRED", failure_reason="Transfer expired prior to execution")
            raise BankingError(
                error_code="AUTHORIZATION_EXPIRED",
                message="Transfer approval has expired",
                http_status=410,
            )

        if txn.status != "AUTHORIZED":
            raise ConflictError(f"Transfer status is {txn.status}; must be AUTHORIZED to execute")

        # Verify summary_hash matches
        if txn.summary_hash != summary_hash:
            raise BankingError(
                error_code="SUMMARY_MISMATCH",
                message="Summary hash mismatch: transfer parameters have been altered.",
                http_status=409,
            )

        # Verify authorization
        auth = repo.get_authorization_by_id(authorization_id)
        if not auth or auth.transaction_id != txn.id:
            raise BankingError(
                error_code="AUTHORIZATION_INVALID",
                message="Authorization does not match transaction",
                http_status=400,
            )
        if auth.status != "VERIFIED":
            raise ConflictError(f"Authorization is {auth.status}; must be VERIFIED")
        auth_exp = to_utc(auth.expires_at)
        if auth_exp and auth_exp < now:
            repo.update_authorization(auth.id, "EXPIRED")
            raise BankingError(
                error_code="AUTHORIZATION_EXPIRED",
                message="Authorization challenge has expired",
                http_status=410,
            )

        # Atomic debit with row locking
        account_stmt = (
            select(BankAccount)
            .where(BankAccount.id == txn.source_account_id)
            .with_for_update()
        )
        source_account = db.scalar(account_stmt)
        if not source_account:
            repo.update_status(txn.id, "FAILED", failure_reason="Source account not found")
            raise NotFoundError("Bank account", txn.source_account_id)

        if source_account.balance_minor < txn.total_debit_minor:
            repo.update_status(txn.id, "FAILED", failure_reason="Insufficient balance at execution")
            raise BankingError(
                error_code="INSUFFICIENT_BALANCE",
                message="Insufficient balance in account to complete transfer.",
                http_status=422,
            )

        # Transition PROCESSING -> COMPLETED
        transition(txn.status, "PROCESSING", context="transfer")
        repo.update_status(txn.id, "PROCESSING")

        # Deduct balance
        source_account.balance_minor -= txn.total_debit_minor

        # Transition to COMPLETED
        transition("PROCESSING", "COMPLETED", context="transfer")
        executed_at = datetime.now(timezone.utc)
        repo.update_status(txn.id, "COMPLETED", executed_at=executed_at)
        repo.update_authorization(auth.id, "CONSUMED", consumed_at=executed_at)

        AuditService.log(
            db=db,
            actor_user_id=user_id,
            actor_type="USER",
            action="TRANSFER_EXECUTE",
            resource_type="bank_transaction",
            resource_id=txn.id,
            outcome="SUCCESS",
            request_id=request_id,
            ip=ip,
            details={
                "amount_minor": txn.amount_minor,
                "fee_minor": txn.fee_minor,
                "total_debit_minor": txn.total_debit_minor,
                "new_balance_minor": source_account.balance_minor,
            },
        )
        return txn

    @staticmethod
    def cancel(
        user_id: str,
        txn_id: str,
        db: Session,
        request_id: Optional[str] = None,
        ip: Optional[str] = None,
    ) -> BankTransaction:
        """Cancel a PENDING_APPROVAL or AUTHORIZED transfer."""
        repo = TransactionRepository(db)
        txn = repo.get_by_id(txn_id, user_id=user_id)
        if not txn:
            raise NotFoundError("Transfer", txn_id)

        transition(txn.status, "CANCELLED", context="transfer")
        repo.update_status(txn.id, "CANCELLED")

        auth = repo.get_authorization(txn.id)
        if auth and auth.status in ["ISSUED", "VERIFIED"]:
            repo.update_authorization(auth.id, "EXPIRED")

        AuditService.log(
            db=db,
            actor_user_id=user_id,
            actor_type="USER",
            action="TRANSFER_CANCEL",
            resource_type="bank_transaction",
            resource_id=txn.id,
            outcome="SUCCESS",
            request_id=request_id,
            ip=ip,
        )
        return txn

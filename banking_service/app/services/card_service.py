"""CardService managing credit card details, statement bills, and payments."""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import BankingSettings
from app.core.errors import BankingError, ConflictError, NotFoundError
from app.core.security import (
    decrypt_field,
    encrypt_field,
    hmac_field,
    sha256_hash,
    verify_pin,
)
from app.models.account import BankAccount
from app.models.credit_card import CreditCard, CreditCardPayment, CreditCardStatement
from app.models.transaction import BankTransaction
from app.models.user import User
from app.repositories.card_repository import CardRepository
from app.schemas.credit_card import CardPaymentRequest
from app.services.audit_service import AuditService


def generate_card_number(prefix: str = "4", length: int = 16) -> str:
    """Generate a valid 16-digit card number satisfying the Luhn algorithm."""
    digits = [int(d) for d in prefix]
    for _ in range(length - 1 - len(prefix)):
        digits.append(secrets.randbelow(10))

    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 0:
            d2 = d * 2
            total += d2 - 9 if d2 > 9 else d2
        else:
            total += d
    check_digit = (10 - (total % 10)) % 10
    digits.append(check_digit)
    return "".join(str(d) for d in digits)


class CardService:
    """Core domain service for credit card operations."""

    @staticmethod
    def create_initial_card(
        user_id: str,
        db: Session,
        settings: BankingSettings,
        network: str | None = None,
        credit_limit_minor: int | None = None,
    ) -> CreditCard:
        """Automatically generate secure card details (number, expiry, CVV) and create an active card for user."""
        if not user_id:
            raise BankingError(
                "INVALID_USER", "User ID is required to create a card", http_status=422
            )

        card_network = network or getattr(settings, "default_card_network", "VISA")
        limit = credit_limit_minor or getattr(settings, "default_card_credit_limit_minor", 20_000_000)

        secret_key = (
            getattr(settings, "secret_key", None)
            or getattr(settings, "jwt_secret", None)
            or "default-banking-secret-key-32-chars-min"
        )

        prefix = "4" if card_network.upper() == "VISA" else "5"

        # Ensure unique card number
        card_number = None
        card_hash = None
        for _ in range(25):
            candidate = generate_card_number(prefix=prefix, length=16)
            cand_hash = hmac_field(candidate, secret_key)
            stmt = select(CreditCard).where(CreditCard.card_number_hash == cand_hash)
            if db.execute(stmt).scalar_one_or_none() is None:
                card_number = candidate
                card_hash = cand_hash
                break

        if not card_number or not card_hash:
            raise BankingError(
                "CARD_GENERATION_FAILED",
                "Could not generate a unique card number",
                http_status=500,
            )

        last4 = card_number[-4:]
        now = datetime.now(timezone.utc)
        expiry_date = f"{now.month:02d}/{(now.year + 5) % 100:02d}"
        cvv = f"{secrets.randbelow(900) + 100}"

        card_number_encrypted = encrypt_field(card_number, secret_key)
        cvv_encrypted = encrypt_field(cvv, secret_key)
        cvv_hash = sha256_hash(cvv)
        card_token = f"tok_{card_network.lower()}_{last4}_{secrets.token_hex(4)}"

        repo = CardRepository(db)
        card = repo.create_card(
            user_id=user_id,
            card_token=card_token,
            last4=last4,
            network=card_network.upper(),
            credit_limit_minor=limit,
            outstanding_minor=0,
            status="ACTIVE",
            card_number_encrypted=card_number_encrypted,
            card_number_hash=card_hash,
            expiry_date=expiry_date,
            cvv_encrypted=cvv_encrypted,
            cvv_hash=cvv_hash,
        )
        return card

    @staticmethod
    def get_card_sensitive_details(
        user_id: str, card_id: str, db: Session, settings: BankingSettings
    ) -> dict[str, str]:
        """Decrypt and return sensitive card details (number, expiry, CVV) for cardholder."""
        card = CardService.get_card(user_id, card_id, db)
        secret_key = (
            getattr(settings, "secret_key", None)
            or getattr(settings, "jwt_secret", None)
            or "default-banking-secret-key-32-chars-min"
        )
        card_number = (
            decrypt_field(card.card_number_encrypted, secret_key)
            if card.card_number_encrypted
            else f"••••••••••••{card.last4}"
        )
        cvv = (
            decrypt_field(card.cvv_encrypted, secret_key)
            if card.cvv_encrypted
            else "•••"
        )
        return {
            "card_id": card.id,
            "card_number": card_number,
            "expiry_date": card.expiry_date or "",
            "cvv": cvv,
        }

    @staticmethod
    def list_cards(user_id: str, db: Session) -> list[CreditCard]:
        """Fetch all cards owned by the user."""
        repo = CardRepository(db)
        return repo.list_for_user(user_id)

    @staticmethod
    def get_card(user_id: str, card_id: str, db: Session) -> CreditCard:
        """Fetch a specific card enforcing ownership."""
        repo = CardRepository(db)
        card = repo.get_by_id(card_id, user_id=user_id)
        if not card:
            raise NotFoundError("Credit card", card_id)
        return card

    @staticmethod
    def get_outstanding(user_id: str, card_id: str, db: Session) -> dict[str, Any]:
        """Get current outstanding and available credit limits."""
        card = CardService.get_card(user_id, card_id, db)
        available = max(0, card.credit_limit_minor - card.outstanding_minor)
        return {
            "card_id": card.id,
            "outstanding_minor": card.outstanding_minor,
            "available_credit_minor": available,
            "currency": "INR",
            "as_of": datetime.now(timezone.utc),
        }

    @staticmethod
    def get_statements(
        user_id: str, card_id: str, page: int, page_size: int, db: Session
    ) -> tuple[list[CreditCardStatement], int]:
        """Fetch paginated statements for a card owned by user."""
        CardService.get_card(user_id, card_id, db)
        repo = CardRepository(db)
        return repo.get_statements(card_id, page=page, page_size=page_size)

    @staticmethod
    def get_current_bill(user_id: str, card_id: str, db: Session) -> CreditCardStatement:
        """Get latest statement bill for the card."""
        CardService.get_card(user_id, card_id, db)
        repo = CardRepository(db)
        statement = repo.get_current_statement(card_id)
        if not statement:
            raise NotFoundError("Current statement for card", card_id)
        return statement

    @staticmethod
    def prepare_payment(
        user_id: str,
        card_id: str,
        data: CardPaymentRequest,
        idempotency_key: str,
        db: Session,
        settings: BankingSettings,
        request_id: Optional[str] = None,
        ip: Optional[str] = None,
    ) -> CreditCardPayment:
        """Prepare a card payment in PENDING_APPROVAL status."""
        card = CardService.get_card(user_id, card_id, db)
        if card.status != "ACTIVE":
            raise ConflictError("Credit card is not ACTIVE")

        repo = CardRepository(db)

        # Idempotency check
        if idempotency_key:
            existing = repo.get_payment_by_idempotency(card.id, idempotency_key)
            if existing:
                return existing

        # Validate source account
        acc = db.scalar(
            select(BankAccount).where(
                BankAccount.id == data.source_account_id,
                BankAccount.user_id == user_id,
            )
        )
        if not acc:
            raise NotFoundError("Source bank account", data.source_account_id)
        if acc.status != "ACTIVE" or acc.verification_status != "VERIFIED":
            raise ConflictError("Source bank account is not ACTIVE and VERIFIED")
        if acc.balance_minor < data.amount_minor:
            raise BankingError(
                error_code="INSUFFICIENT_BALANCE",
                message="Source account has insufficient balance for this card payment.",
                http_status=422,
            )

        ref_timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        reference = f"CCPAY{ref_timestamp}{secrets.token_hex(2).upper()}"

        payment = repo.create_payment(
            card_id=card.id,
            statement_id=data.statement_id,
            source_account_id=data.source_account_id,
            amount_minor=data.amount_minor,
            reference=reference,
            idempotency_key=idempotency_key,
        )

        AuditService.log(
            db=db,
            actor_user_id=user_id,
            actor_type="USER",
            action="CARD_PAYMENT_PREPARE",
            resource_type="credit_card_payment",
            resource_id=payment.id,
            outcome="SUCCESS",
            request_id=request_id,
            ip=ip,
            details={"card_id": card.id, "amount_minor": data.amount_minor},
        )
        return payment

    @staticmethod
    def authorize_payment(
        user_id: str,
        payment_id: str,
        pin_or_otp: str | None,
        db: Session,
        settings: BankingSettings,
        request_id: Optional[str] = None,
        ip: Optional[str] = None,
    ) -> CreditCardPayment:
        """Verify customer PIN and authorize card payment."""
        repo = CardRepository(db)
        payment = repo.get_payment(payment_id)
        if not payment:
            raise NotFoundError("Card payment", payment_id)

        # Verify card belongs to user
        CardService.get_card(user_id, payment.card_id, db)

        if payment.status != "PENDING_APPROVAL":
            raise ConflictError(f"Payment is {payment.status}, cannot authorize")

        user = db.scalar(select(User).where(User.id == user_id))
        if not user or not user.transaction_pin_hash:
            raise ConflictError("Transaction PIN not set")

        if not pin_or_otp or not verify_pin(pin_or_otp, user.transaction_pin_hash):
            AuditService.log(
                db=db,
                actor_user_id=user_id,
                actor_type="USER",
                action="CARD_PAYMENT_AUTHORIZE",
                resource_type="credit_card_payment",
                resource_id=payment.id,
                outcome="FAILURE",
                request_id=request_id,
                ip=ip,
            )
            raise BankingError(
                error_code="AUTHORIZATION_INVALID",
                message="Invalid transaction PIN provided",
                http_status=400,
            )

        repo.update_payment_status(payment.id, "AUTHORIZED")

        AuditService.log(
            db=db,
            actor_user_id=user_id,
            actor_type="USER",
            action="CARD_PAYMENT_AUTHORIZE",
            resource_type="credit_card_payment",
            resource_id=payment.id,
            outcome="SUCCESS",
            request_id=request_id,
            ip=ip,
        )
        return payment

    @staticmethod
    def execute_payment(
        user_id: str,
        payment_id: str,
        authorization_id: Optional[str],
        db: Session,
        settings: BankingSettings,
        request_id: Optional[str] = None,
        ip: Optional[str] = None,
    ) -> CreditCardPayment:
        """Atomically deduct balance, reduce card outstanding, and mark payment COMPLETED."""
        repo = CardRepository(db)
        payment = repo.get_payment(payment_id)
        if not payment:
            raise NotFoundError("Card payment", payment_id)

        card = CardService.get_card(user_id, payment.card_id, db)

        if payment.status == "COMPLETED":
            return payment

        if payment.status != "AUTHORIZED":
            raise ConflictError(f"Payment status is {payment.status}; must be AUTHORIZED to execute")

        # Atomic debit from source bank account
        acc = db.scalar(
            select(BankAccount)
            .where(BankAccount.id == payment.source_account_id)
            .with_for_update()
        )
        if not acc or acc.balance_minor < payment.amount_minor:
            repo.update_payment_status(payment.id, "FAILED")
            raise BankingError(
                error_code="INSUFFICIENT_BALANCE",
                message="Insufficient balance in account to complete card payment.",
                http_status=422,
            )

        acc.balance_minor -= payment.amount_minor

        # Reduce card outstanding
        card.outstanding_minor = max(0, card.outstanding_minor - payment.amount_minor)

        # Update statement if linked
        if payment.statement_id:
            statement = db.scalar(
                select(CreditCardStatement).where(CreditCardStatement.id == payment.statement_id)
            )
            if statement:
                if payment.amount_minor >= statement.total_due_minor:
                    statement.status = "PAID"
                else:
                    statement.status = "PARTIALLY_PAID"

        # Create ledger transaction record
        ref_timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        txn_ref = f"TXN{ref_timestamp}{secrets.token_hex(2).upper()}"
        txn = BankTransaction(
            id=str(uuid.uuid4()),
            reference=txn_ref,
            user_id=user_id,
            source_account_id=payment.source_account_id,
            type="CARD_PAYMENT",
            amount_minor=payment.amount_minor,
            fee_minor=0,
            total_debit_minor=payment.amount_minor,
            currency="INR",
            status="COMPLETED",
            channel="INTERNAL",
            remark=f"Payment for card ending {card.last4}",
            executed_at=datetime.now(timezone.utc),
        )
        db.add(txn)
        db.flush()

        repo.update_payment_status(payment.id, "COMPLETED", transaction_id=txn.id)

        AuditService.log(
            db=db,
            actor_user_id=user_id,
            actor_type="USER",
            action="CARD_PAYMENT_EXECUTE",
            resource_type="credit_card_payment",
            resource_id=payment.id,
            outcome="SUCCESS",
            request_id=request_id,
            ip=ip,
            details={
                "amount_minor": payment.amount_minor,
                "card_outstanding_after": card.outstanding_minor,
                "transaction_id": txn.id,
            },
        )
        return payment

    @staticmethod
    def list_payments(user_id: str, card_id: str, db: Session) -> list[CreditCardPayment]:
        """List all payments for a given card."""
        CardService.get_card(user_id, card_id, db)
        repo = CardRepository(db)
        return repo.list_payments(card_id, user_id=user_id)

    @staticmethod
    def get_payment(user_id: str, payment_id: str, db: Session) -> CreditCardPayment:
        """Fetch a specific payment checking user ownership."""
        repo = CardRepository(db)
        payment = repo.get_payment(payment_id)
        if not payment:
            raise NotFoundError("Card payment", payment_id)
        CardService.get_card(user_id, payment.card_id, db)
        return payment

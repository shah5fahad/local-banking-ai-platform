"""Repository for CreditCard, CreditCardStatement, and CreditCardPayment."""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.credit_card import CreditCard, CreditCardPayment, CreditCardStatement


class CardRepository:
    """Repository handling cards, statements, and card payments."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create_card(
        self,
        user_id: str,
        card_token: str,
        last4: str,
        network: str,
        credit_limit_minor: int,
        outstanding_minor: int = 0,
        status: str = "ACTIVE",
        card_number_encrypted: Optional[str] = None,
        card_number_hash: Optional[str] = None,
        expiry_date: Optional[str] = None,
        cvv_encrypted: Optional[str] = None,
        cvv_hash: Optional[str] = None,
    ) -> CreditCard:
        """Create and persist a new CreditCard entity."""
        card = CreditCard(
            id=str(uuid.uuid4()),
            user_id=user_id,
            card_token=card_token,
            last4=last4,
            network=network,
            credit_limit_minor=credit_limit_minor,
            outstanding_minor=outstanding_minor,
            status=status,
            card_number_encrypted=card_number_encrypted,
            card_number_hash=card_number_hash,
            expiry_date=expiry_date,
            cvv_encrypted=cvv_encrypted,
            cvv_hash=cvv_hash,
        )
        self.session.add(card)
        self.session.flush()
        self.session.refresh(card)
        return card

    def list_for_user(self, user_id: str) -> list[CreditCard]:
        """Fetch all credit cards owned by user."""
        stmt = (
            select(CreditCard)
            .where(CreditCard.user_id == user_id)
            .order_by(CreditCard.created_at.desc())
        )
        return list(self.session.scalars(stmt).all())

    def get_by_id(self, id: str, user_id: Optional[str] = None) -> CreditCard | None:
        """Fetch credit card by ID, enforcing user ownership."""
        stmt = select(CreditCard).where(CreditCard.id == id)
        if user_id is not None:
            stmt = stmt.where(CreditCard.user_id == user_id)
        return self.session.scalar(stmt)

    def get_statements(
        self, card_id: str, page: int = 1, page_size: int = 20
    ) -> tuple[list[CreditCardStatement], int]:
        """Fetch paginated statements for a card."""
        count_stmt = select(func.count(CreditCardStatement.id)).where(
            CreditCardStatement.card_id == card_id
        )
        total = self.session.scalar(count_stmt) or 0

        offset = (max(page, 1) - 1) * page_size
        stmt = (
            select(CreditCardStatement)
            .where(CreditCardStatement.card_id == card_id)
            .order_by(CreditCardStatement.period_end.desc())
            .offset(offset)
            .limit(page_size)
        )
        items = list(self.session.scalars(stmt).all())
        return items, total

    def get_current_statement(self, card_id: str) -> CreditCardStatement | None:
        """Fetch the most recent statement for a card."""
        stmt = (
            select(CreditCardStatement)
            .where(CreditCardStatement.card_id == card_id)
            .order_by(CreditCardStatement.period_end.desc())
            .limit(1)
        )
        return self.session.scalar(stmt)

    def create_payment(
        self,
        card_id: str,
        statement_id: Optional[str],
        source_account_id: str,
        amount_minor: int,
        reference: str,
        idempotency_key: Optional[str],
    ) -> CreditCardPayment:
        """Create a pending credit card payment."""
        payment = CreditCardPayment(
            id=str(uuid.uuid4()),
            reference=reference,
            card_id=card_id,
            statement_id=statement_id,
            source_account_id=source_account_id,
            amount_minor=amount_minor,
            status="PENDING_APPROVAL",
            idempotency_key=idempotency_key,
        )
        self.session.add(payment)
        self.session.flush()
        return payment

    def get_payment(self, id: str) -> CreditCardPayment | None:
        """Fetch payment by ID."""
        stmt = select(CreditCardPayment).where(CreditCardPayment.id == id)
        return self.session.scalar(stmt)

    def get_payment_by_idempotency(
        self, card_id: str, key: str
    ) -> CreditCardPayment | None:
        """Fetch payment by card ID and idempotency key."""
        stmt = select(CreditCardPayment).where(
            CreditCardPayment.card_id == card_id,
            CreditCardPayment.idempotency_key == key,
        )
        return self.session.scalar(stmt)

    def list_payments(self, card_id: str, user_id: str) -> list[CreditCardPayment]:
        """List payments for a specific card ensuring ownership."""
        stmt = (
            select(CreditCardPayment)
            .join(CreditCard, CreditCardPayment.card_id == CreditCard.id)
            .where(CreditCardPayment.card_id == card_id, CreditCard.user_id == user_id)
            .order_by(CreditCardPayment.created_at.desc())
        )
        return list(self.session.scalars(stmt).all())

    def update_payment_status(
        self,
        id: str,
        status: str,
        transaction_id: Optional[str] = None,
    ) -> None:
        """Update payment status and linked bank transaction."""
        values: dict[str, Any] = {
            "status": status,
            "updated_at": datetime.now(timezone.utc),
        }
        if transaction_id is not None:
            values["transaction_id"] = transaction_id

        stmt = update(CreditCardPayment).where(CreditCardPayment.id == id).values(**values)
        self.session.execute(stmt)
        self.session.flush()

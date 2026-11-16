"""Loan repository handling LoanOffer and LoanApplication database records."""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.loan import LoanApplication, LoanOffer


class LoanRepository:
    """Repository handling loan offers and loan applications."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create_offer(
        self,
        loan_type: str,
        max_amount_minor: int,
        rate_bps: int,
        min_tenure_months: int,
        max_tenure_months: int,
        valid_till: datetime,
        user_id: Optional[str] = None,
        name: Optional[str] = None,
        terms: Optional[str] = None,
        status: str = "ACTIVE",
    ) -> LoanOffer:
        """Create and persist a new loan offer."""
        offer = LoanOffer(
            id=str(uuid.uuid4()),
            user_id=user_id,
            loan_type=loan_type,
            max_amount_minor=max_amount_minor,
            rate_bps=rate_bps,
            min_tenure_months=min_tenure_months,
            max_tenure_months=max_tenure_months,
            valid_till=valid_till,
            name=name,
            terms=terms,
            status=status,
        )
        self.session.add(offer)
        self.session.flush()
        return offer

    def get_offers_for_user(self, user_id: str) -> list[LoanOffer]:
        """Fetch all active loan offers applicable to user (user-specific or general)."""
        now = datetime.now(timezone.utc)
        stmt = (
            select(LoanOffer)
            .where(
                or_(LoanOffer.user_id == user_id, LoanOffer.user_id.is_(None)),
                LoanOffer.status == "ACTIVE",
                LoanOffer.valid_till >= now,
            )
            .order_by(LoanOffer.max_amount_minor.desc())
        )
        return list(self.session.scalars(stmt).all())

    def get_offer(self, offer_id: str, user_id: Optional[str] = None) -> LoanOffer | None:
        """Fetch loan offer by ID."""
        stmt = select(LoanOffer).where(LoanOffer.id == offer_id)
        if user_id is not None:
            stmt = stmt.where(or_(LoanOffer.user_id == user_id, LoanOffer.user_id.is_(None)))
        return self.session.scalar(stmt)

    def create_application(
        self,
        user_id: str,
        offer_id: Optional[str],
        loan_type: str,
        amount_minor: int,
        tenure_months: int,
        rate_bps: int,
        employment_type: str,
        employer: str,
        monthly_income_minor: int,
        idempotency_key: Optional[str],
        status: str = "SUBMITTED",
        decision_reason: Optional[str] = None,
    ) -> LoanApplication:
        """Create and persist a new loan application."""
        ref_timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        reference = f"LN{ref_timestamp}{secrets.token_hex(2).upper()}"

        app = LoanApplication(
            id=str(uuid.uuid4()),
            reference=reference,
            user_id=user_id,
            offer_id=offer_id,
            loan_type=loan_type,
            amount_minor=amount_minor,
            tenure_months=tenure_months,
            rate_bps=rate_bps,
            employment_type=employment_type,
            employer=employer,
            monthly_income_minor=monthly_income_minor,
            status=status,
            decision_reason=decision_reason,
            idempotency_key=idempotency_key,
        )
        self.session.add(app)
        self.session.flush()
        return app

    def get_application(self, id: str, user_id: Optional[str] = None) -> LoanApplication | None:
        """Fetch application by ID enforcing user ownership."""
        stmt = select(LoanApplication).where(LoanApplication.id == id)
        if user_id is not None:
            stmt = stmt.where(LoanApplication.user_id == user_id)
        return self.session.scalar(stmt)

    def get_by_idempotency_key(
        self, user_id: str, key: str
    ) -> LoanApplication | None:
        """Find existing application by user and idempotency key."""
        stmt = select(LoanApplication).where(
            LoanApplication.user_id == user_id,
            LoanApplication.idempotency_key == key,
        )
        return self.session.scalar(stmt)

    def list_applications(self, user_id: str) -> list[LoanApplication]:
        """List all loan applications submitted by user."""
        stmt = (
            select(LoanApplication)
            .where(LoanApplication.user_id == user_id)
            .order_by(LoanApplication.created_at.desc())
        )
        return list(self.session.scalars(stmt).all())

    def list_active(self, user_id: str) -> list[LoanApplication]:
        """List active (APPROVED) loans for user."""
        stmt = (
            select(LoanApplication)
            .where(
                LoanApplication.user_id == user_id,
                LoanApplication.status == "APPROVED",
            )
            .order_by(LoanApplication.created_at.desc())
        )
        return list(self.session.scalars(stmt).all())

    def count_active_loans(self, user_id: str) -> int:
        """Count active APPROVED loans for eligibility check."""
        stmt = select(func.count(LoanApplication.id)).where(
            LoanApplication.user_id == user_id,
            LoanApplication.status == "APPROVED",
        )
        return int(self.session.scalar(stmt) or 0)

"""LoanService managing offers, applications, eligibility evaluation, and EMI schedules."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.config import BankingSettings
from app.core.errors import BankingError, ConflictError, NotFoundError
from app.models.loan import LoanApplication, LoanOffer
from app.repositories.loan_repository import LoanRepository
from app.schemas.loan import EligibilityRequest, LoanApplicationRequest
from app.services.audit_service import AuditService
from app.services.eligibility_rules import (
    DEFAULT_RATE_BPS,
    calculate_emi_minor,
    check_eligibility,
)


class LoanService:
    """Core domain service for loans."""

    @staticmethod
    def provision_initial_loan_offers(
        user_id: str,
        db: Session,
        settings: BankingSettings | None = None,
    ) -> list[LoanOffer]:
        """Automatically create and link at least three loan offers (Home, Car/Auto, Personal) for new user."""
        if not user_id:
            raise BankingError(
                "INVALID_USER", "User ID is required to create loan offers", http_status=422
            )

        repo = LoanRepository(db)
        now = datetime.now(timezone.utc)

        offers_data = [
            {
                "loan_type": "HOME",
                "name": "Pre-Approved Home Loan",
                "max_amount_minor": 500_000_000,  # ₹5,000,000 (50 Lakhs)
                "rate_bps": 850,                   # 8.50%
                "min_tenure_months": 60,
                "max_tenure_months": 240,
                "valid_till": now + timedelta(days=365),
                "terms": "Floating rate linked to RBI repo rate; financing up to 80% of property cost; zero prepayment penalty.",
            },
            {
                "loan_type": "AUTO",
                "name": "Prime Car & Auto Loan",
                "max_amount_minor": 150_000_000,  # ₹1,500,000 (15 Lakhs)
                "rate_bps": 925,                   # 9.25%
                "min_tenure_months": 12,
                "max_tenure_months": 84,
                "valid_till": now + timedelta(days=180),
                "terms": "Fixed interest rate; financing up to 90% on-road price for passenger vehicles; minimal documentation.",
            },
            {
                "loan_type": "PERSONAL",
                "name": "Instant Express Personal Loan",
                "max_amount_minor": 50_000_000,   # ₹500,000 (5 Lakhs)
                "rate_bps": 1050,                  # 10.50%
                "min_tenure_months": 12,
                "max_tenure_months": 60,
                "valid_till": now + timedelta(days=90),
                "terms": "Instant disbursement into primary account; unsecured personal credit with flexible monthly repayment.",
            },
        ]

        created_offers: list[LoanOffer] = []
        for data in offers_data:
            offer = repo.create_offer(
                user_id=user_id,
                loan_type=data["loan_type"],
                name=data["name"],
                max_amount_minor=data["max_amount_minor"],
                rate_bps=data["rate_bps"],
                min_tenure_months=data["min_tenure_months"],
                max_tenure_months=data["max_tenure_months"],
                valid_till=data["valid_till"],
                terms=data["terms"],
                status="ACTIVE",
            )
            created_offers.append(offer)

        return created_offers

    @staticmethod
    def get_offers(user_id: str, db: Session) -> list[LoanOffer]:
        """Fetch all available loan offers for a user."""
        repo = LoanRepository(db)
        return repo.get_offers_for_user(user_id)

    @staticmethod
    def get_offer(user_id: str, offer_id: str, db: Session) -> LoanOffer:
        """Fetch a specific loan offer."""
        repo = LoanRepository(db)
        offer = repo.get_offer(offer_id, user_id=user_id)
        if not offer:
            raise NotFoundError("Loan offer", offer_id)
        return offer

    @staticmethod
    def evaluate_eligibility(
        user_id: str,
        data: EligibilityRequest,
        db: Session,
        rate_bps: Optional[int] = None,
    ) -> tuple[bool, int, list[str]]:
        """Evaluate loan eligibility rules for applicant."""
        repo = LoanRepository(db)
        existing_loans = repo.count_active_loans(user_id)
        return check_eligibility(
            loan_type=data.loan_type,
            amount_minor=data.amount_minor,
            tenure_months=data.tenure_months,
            monthly_income_minor=data.monthly_income_minor,
            existing_loans=existing_loans,
            rate_bps=rate_bps,
        )

    @staticmethod
    def apply(
        user_id: str,
        data: LoanApplicationRequest,
        idempotency_key: str,
        db: Session,
        request_id: Optional[str] = None,
        ip: Optional[str] = None,
    ) -> LoanApplication:
        """Submit loan application; auto-approves if eligible."""
        repo = LoanRepository(db)

        # 1. Idempotency check
        if idempotency_key:
            existing = repo.get_by_idempotency_key(user_id, idempotency_key)
            if existing:
                return existing

        rate_bps = DEFAULT_RATE_BPS.get(data.loan_type.upper(), 1200)
        offer_id = data.offer_id

        # 2. Offer validation if provided
        if offer_id:
            offer = repo.get_offer(offer_id, user_id=user_id)
            if not offer:
                raise NotFoundError("Loan offer", offer_id)
            if offer.status != "ACTIVE" or offer.valid_till < datetime.now(timezone.utc):
                raise ConflictError("Selected loan offer is no longer valid or active")
            rate_bps = offer.rate_bps

        # 3. Eligibility evaluation
        existing_loans = repo.count_active_loans(user_id)
        eligible, _, reasons = check_eligibility(
            loan_type=data.loan_type,
            amount_minor=data.amount_minor,
            tenure_months=data.tenure_months,
            monthly_income_minor=data.monthly_income_minor,
            existing_loans=existing_loans,
            rate_bps=rate_bps,
        )

        status = "APPROVED" if eligible else "REJECTED"
        decision_reason = (
            "Instant approval based on credit profile and income verification"
            if eligible
            else "; ".join(reasons)
        )

        app = repo.create_application(
            user_id=user_id,
            offer_id=offer_id,
            loan_type=data.loan_type,
            amount_minor=data.amount_minor,
            tenure_months=data.tenure_months,
            rate_bps=rate_bps,
            employment_type=data.employment_type,
            employer=data.employer,
            monthly_income_minor=data.monthly_income_minor,
            idempotency_key=idempotency_key,
            status=status,
            decision_reason=decision_reason,
        )

        AuditService.log(
            db=db,
            actor_user_id=user_id,
            actor_type="USER",
            action="LOAN_APPLY",
            resource_type="loan_application",
            resource_id=app.id,
            outcome="SUCCESS" if eligible else "FAILURE",
            request_id=request_id,
            ip=ip,
            details={
                "amount_minor": app.amount_minor,
                "status": status,
                "decision_reason": decision_reason,
            },
        )
        return app

    @staticmethod
    def list_applications(user_id: str, db: Session) -> list[LoanApplication]:
        """List user's submitted loan applications."""
        repo = LoanRepository(db)
        return repo.list_applications(user_id)

    @staticmethod
    def get_application(user_id: str, application_id: str, db: Session) -> LoanApplication:
        """Fetch a specific loan application."""
        repo = LoanRepository(db)
        app = repo.get_application(application_id, user_id=user_id)
        if not app:
            raise NotFoundError("Loan application", application_id)
        return app

    @staticmethod
    def list_active_loans(user_id: str, db: Session) -> list[LoanApplication]:
        """List user's active APPROVED loans."""
        repo = LoanRepository(db)
        return repo.list_active(user_id)

    @staticmethod
    def get_repayment(user_id: str, loan_id: str, db: Session) -> dict[str, Any]:
        """Generate monthly amortization schedule for a loan."""
        repo = LoanRepository(db)
        app = repo.get_application(loan_id, user_id=user_id)
        if not app:
            raise NotFoundError("Loan", loan_id)

        principal = app.amount_minor
        rate_bps = app.rate_bps
        tenure = app.tenure_months

        monthly_emi = calculate_emi_minor(principal, rate_bps, tenure)
        annual_rate = rate_bps / 10000.0
        r = annual_rate / 12.0

        schedule: list[dict[str, Any]] = []
        current_balance = principal
        total_interest = 0

        for month in range(1, tenure + 1):
            interest = int(round(current_balance * r))
            principal_paid = min(monthly_emi - interest, current_balance)
            closing_balance = max(0, current_balance - principal_paid)
            total_interest += interest

            schedule.append({
                "month": month,
                "opening_balance_minor": current_balance,
                "emi_minor": monthly_emi,
                "principal_minor": principal_paid,
                "interest_minor": interest,
                "closing_balance_minor": closing_balance,
            })
            current_balance = closing_balance
            if current_balance <= 0:
                break

        total_payable = principal + total_interest

        return {
            "loan_id": app.id,
            "monthly_emi_minor": monthly_emi,
            "total_payable_minor": total_payable,
            "tenure_months": tenure,
            "rate_bps": rate_bps,
            "schedule": schedule,
        }

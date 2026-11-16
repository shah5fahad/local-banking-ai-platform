"""Pydantic schemas for Loans, Offers, Eligibility, and Repayment."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class LoanOfferResponse(BaseModel):
    """Pre-approved loan offer representation."""

    id: str
    loan_type: str
    max_amount_minor: int
    rate_bps: int
    min_tenure_months: int
    max_tenure_months: int
    valid_till: datetime
    status: str
    name: Optional[str] = None
    terms: Optional[str] = None
    user_id: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class EligibilityRequest(BaseModel):
    """Payload to evaluate loan eligibility."""

    loan_type: str = Field(..., description="PERSONAL, HOME, AUTO")
    amount_minor: int = Field(..., gt=0, description="Requested amount in minor units")
    tenure_months: int = Field(..., gt=0, description="Tenure in months")
    monthly_income_minor: int = Field(..., gt=0, description="Monthly income in minor units")


class EligibilityResponse(BaseModel):
    """Outcome of loan eligibility check."""

    eligible: bool
    max_amount_minor: int
    reasons: list[str] = []


class LoanApplicationRequest(BaseModel):
    """Payload to submit a loan application."""

    offer_id: Optional[str] = None
    loan_type: str = Field(..., description="PERSONAL, HOME, AUTO")
    amount_minor: int = Field(..., gt=0)
    tenure_months: int = Field(..., gt=0)
    employment_type: str = Field(..., max_length=64)
    employer: str = Field(..., max_length=255)
    monthly_income_minor: int = Field(..., gt=0)


class LoanApplicationResponse(BaseModel):
    """Loan application status and details."""

    id: str
    reference: str
    loan_type: str
    amount_minor: int
    tenure_months: int
    rate_bps: int
    status: str
    decision_reason: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RepaymentScheduleResponse(BaseModel):
    """Repayment schedule with amortization."""

    loan_id: str
    monthly_emi_minor: int
    total_payable_minor: int
    tenure_months: int
    rate_bps: int
    schedule: list[dict[str, Any]]

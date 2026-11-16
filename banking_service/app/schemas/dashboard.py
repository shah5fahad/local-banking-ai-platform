"""Pydantic schemas for customer dashboard."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.schemas.account import AccountResponse
from app.schemas.credit_card import CreditCardResponse
from app.schemas.loan import LoanOfferResponse
from app.schemas.user import UserResponse


class CustomerDashboardResponse(BaseModel):
    """Aggregated customer dashboard data for authenticated user."""

    user: UserResponse
    accounts: list[AccountResponse]
    cards: list[CreditCardResponse]
    loan_offers: list[LoanOfferResponse]
    total_balance_minor: int
    total_credit_limit_minor: int
    total_available_credit_minor: int
    as_of: datetime

    model_config = ConfigDict(from_attributes=True)

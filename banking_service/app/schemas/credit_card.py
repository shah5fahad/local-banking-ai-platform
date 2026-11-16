"""Pydantic schemas for Credit Cards, Statements, and Payments."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class CreditCardResponse(BaseModel):
    """Credit card details (masked, no PAN/CVV)."""

    id: str
    user_id: str
    last4: str
    network: str
    credit_limit_minor: int
    outstanding_minor: int
    status: str
    card_number_masked: Optional[str] = None
    expiry_date: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SensitiveCardDetailsResponse(BaseModel):
    """Card details including full card number, expiry, and CVV for cardholder view."""

    card_id: str
    card_number: str
    expiry_date: str
    cvv: str


class OutstandingResponse(BaseModel):
    """Card outstanding balance and available credit."""

    card_id: str
    outstanding_minor: int
    available_credit_minor: int
    currency: str = "INR"
    as_of: datetime


class StatementResponse(BaseModel):
    """Credit card billing statement."""

    id: str
    card_id: str
    period_start: datetime
    period_end: datetime
    total_due_minor: int
    min_due_minor: int
    due_date: datetime
    status: str

    model_config = ConfigDict(from_attributes=True)


class StatementListResponse(BaseModel):
    """Paginated statements response."""

    items: list[StatementResponse]
    total: int
    page: int
    page_size: int


class CardPaymentRequest(BaseModel):
    """Payload to initiate a credit card bill payment."""

    statement_id: Optional[str] = None
    source_account_id: str = Field(..., description="Source bank account UUID")
    amount_minor: int = Field(..., gt=0, description="Payment amount in minor units")


class AuthorizePaymentRequest(BaseModel):
    """Authorization payload for card payment."""

    pin: Optional[str] = None
    otp: Optional[str] = None


class ExecutePaymentRequest(BaseModel):
    """Execution payload for card payment."""

    authorization_id: Optional[str] = None


class CardPaymentResponse(BaseModel):
    """Credit card payment status."""

    id: str
    reference: str
    status: str
    amount_minor: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

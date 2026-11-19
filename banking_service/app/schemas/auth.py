"""Pydantic schemas for authentication and session management."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.account import AccountResponse
from app.schemas.credit_card import CreditCardResponse
from app.schemas.loan import LoanOfferResponse

_UPPERCASE_RE = re.compile(r"[A-Z]")
_LOWERCASE_RE = re.compile(r"[a-z]")
_DIGIT_RE = re.compile(r"[0-9]")
_SPECIAL_RE = re.compile(r"[^A-Za-z0-9]")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RegisterRequest(BaseModel):
    """Payload for user registration."""

    email: str = Field(..., min_length=3, max_length=255)
    phone: str = Field(
        ...,
        description="E.164 phone number, e.g. +919876543210 or 10-15 digits",
        min_length=10,
        max_length=20,
    )
    full_name: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=12)
    pin: str = Field(
        ...,
        description="Required 4-6 digit numeric transaction PIN",
    )

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError("Invalid email address format")
        return v

    @field_validator("password")
    @classmethod
    def validate_password_complexity(cls, v: str) -> str:
        if len(v) < 12:
            raise ValueError("Password must be at least 12 characters long")
        if not _UPPERCASE_RE.search(v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not _LOWERCASE_RE.search(v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not _DIGIT_RE.search(v):
            raise ValueError("Password must contain at least one digit")
        if not _SPECIAL_RE.search(v):
            raise ValueError("Password must contain at least one special character")
        return v

    @field_validator("pin")
    @classmethod
    def validate_pin_format(cls, v: str) -> str:
        if not v or not re.match(r"^\d{4,6}$", v.strip()):
            raise ValueError("Transaction PIN is required and must be 4 to 6 numeric digits")
        return v.strip()


class RegisterResponse(BaseModel):
    """Response returned upon successful registration."""

    id: str
    email: str
    full_name: str
    transaction_pin_set: bool = True
    account_id: Optional[str] = None
    account_number_masked: Optional[str] = None
    account: Optional[AccountResponse] = None
    card_id: Optional[str] = None
    card_last4: Optional[str] = None
    card: Optional[CreditCardResponse] = None
    loan_offers: Optional[list[LoanOfferResponse]] = None

    model_config = ConfigDict(from_attributes=True)


class LoginRequest(BaseModel):
    """Payload for user login."""

    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=1)


class TokenResponse(BaseModel):
    """JWT token pair response."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 900  # 15 minutes in seconds


class RefreshRequest(BaseModel):
    """Payload to refresh an access token."""

    refresh_token: str = Field(..., min_length=1)


class SessionResponse(BaseModel):
    """Details of an active user session."""

    id: str
    user_agent: str | None = None
    ip: str | None = None
    created_at: datetime
    expires_at: datetime
    is_current: bool = False

    model_config = ConfigDict(from_attributes=True)

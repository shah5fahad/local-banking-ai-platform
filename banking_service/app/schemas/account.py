"""Pydantic schemas for BankAccount domain."""
from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator


class CreateAccountRequest(BaseModel):
    """Request schema for linking a new bank account."""

    holder_name: str = Field(..., min_length=2, max_length=255)
    account_number: str
    ifsc: str
    bank_name: str = Field(..., min_length=2, max_length=255)
    branch_name: str | None = None
    account_type: str = Field(default="SAVINGS")

    @field_validator("account_number")
    @classmethod
    def validate_account_number(cls, v: str) -> str:
        cleaned = v.strip()
        if not re.match(r"^\d{9,18}$", cleaned):
            raise ValueError("Account number must be between 9 and 18 numeric digits")
        return cleaned

    @field_validator("ifsc")
    @classmethod
    def validate_ifsc(cls, v: str) -> str:
        cleaned = v.strip().upper()
        if not re.match(r"^[A-Z]{4}0[A-Z0-9]{6}$", cleaned):
            raise ValueError(
                "IFSC code must match pattern '^[A-Z]{4}0[A-Z0-9]{6}$' (e.g. HDFC0001234)"
            )
        return cleaned

    @field_validator("account_type")
    @classmethod
    def validate_account_type(cls, v: str) -> str:
        cleaned = v.strip().upper()
        if cleaned not in ("SAVINGS", "CURRENT", "SALARY"):
            raise ValueError("account_type must be SAVINGS, CURRENT, or SALARY")
        return cleaned


class AccountResponse(BaseModel):
    """Bank account response schema returning masked account number."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    holder_name: str
    account_number_masked: str
    account_number_last4: str
    ifsc: str
    bank_name: str
    branch_name: str | None
    account_type: str
    balance_minor: int
    currency: str
    verification_status: str
    status: str
    created_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def balance_rupees(self) -> float:
        """Account balance in rupees."""
        return round(self.balance_minor / 100.0, 2)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def balance_formatted(self) -> str:
        """Formatted balance in INR (e.g. ₹5,000.00)."""
        return f"₹{self.balance_minor / 100.0:,.2f}"


class UpdateAccountRequest(BaseModel):
    """Request schema for updating non-key account fields."""

    holder_name: str | None = None
    bank_name: str | None = None
    branch_name: str | None = None


class BalanceResponse(BaseModel):
    """Account balance response."""

    bank_name: str = "Primary Bank"
    available_minor: int
    currency: str
    as_of: str

    model_config = ConfigDict(from_attributes=True)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def available_rupees(self) -> float:
        """Available balance in rupees."""
        return round(self.available_minor / 100.0, 2)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def available_formatted(self) -> str:
        """Formatted available balance in INR (e.g. ₹5,000.00)."""
        return f"₹{self.available_minor / 100.0:,.2f}"

    @field_validator("as_of", mode="before")
    @classmethod
    def format_as_of(cls, v: datetime | str) -> str:
        if isinstance(v, datetime):
            return v.strftime("%d %b %Y, %I:%M %p UTC")
        return str(v)


class VerifyAccountResponse(BaseModel):
    """Account verification response."""

    verification_status: str
    message: str

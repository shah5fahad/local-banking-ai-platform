"""Pydantic schemas for User domain."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class UserResponse(BaseModel):
    """Public user profile response."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    phone: str
    full_name: str
    is_active: bool
    created_at: datetime
    roles: list[str]

    @field_validator("roles", mode="before")
    @classmethod
    def serialize_roles(cls, v: Any) -> list[str]:
        if not v:
            return ["CUSTOMER"]
        if isinstance(v, list):
            result: list[str] = []
            for r in v:
                if hasattr(r, "name"):
                    result.append(getattr(r, "name"))
                elif hasattr(r, "role") and hasattr(getattr(r, "role"), "name"):
                    result.append(getattr(getattr(r, "role"), "name"))
                else:
                    result.append(str(r))
            return result or ["CUSTOMER"]
        return ["CUSTOMER"]


class UpdateUserRequest(BaseModel):
    """Request schema for updating user profile."""

    full_name: str | None = None
    phone: str | None = None

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str | None) -> str | None:
        if v is not None:
            cleaned = v.strip()
            if not re.match(r"^\+?[0-9]{10,15}$", cleaned):
                raise ValueError(
                    "Phone number must be between 10 and 15 digits, optionally with leading '+'"
                )
            return cleaned
        return v


class ChangePasswordRequest(BaseModel):
    """Request schema for password change."""

    current_password: str
    new_password: str = Field(
        ..., min_length=12, description="New password, minimum 12 characters"
    )


class ResetPinRequest(BaseModel):
    """Request schema for resetting or setting transaction PIN with password verification."""

    current_password: str = Field(
        ..., description="Current login password for verification"
    )
    new_pin: str = Field(
        ..., description="New 4-6 digit numeric transaction PIN"
    )
    confirm_pin: Optional[str] = Field(
        default=None, description="Confirmation of new PIN"
    )

    @property
    def password(self) -> str:
        return self.current_password

    @property
    def pin(self) -> str:
        return self.new_pin

    @model_validator(mode="before")
    @classmethod
    def populate_aliases(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # allow password as fallback for current_password
            if "password" in data and "current_password" not in data:
                data["current_password"] = data["password"]
            # allow pin as fallback for new_pin
            if "pin" in data and "new_pin" not in data:
                data["new_pin"] = data["pin"]
        return data

    @field_validator("new_pin")
    @classmethod
    def validate_new_pin(cls, v: str) -> str:
        cleaned = v.strip() if v else ""
        if not re.match(r"^\d{4,6}$", cleaned):
            raise ValueError("Transaction PIN must be 4 to 6 numeric digits")
        return cleaned

    @model_validator(mode="after")
    def validate_confirmation(self) -> ResetPinRequest:
        if self.confirm_pin is not None:
            cleaned_confirm = self.confirm_pin.strip() if self.confirm_pin else ""
            if cleaned_confirm != self.new_pin:
                raise ValueError("PIN confirmation does not match new PIN")
        return self


class SetPinRequest(ResetPinRequest):
    """Request schema for setting or updating transaction PIN (alias/compatible with ResetPinRequest)."""

    pass


class ResetPinResponse(BaseModel):
    """Response schema after successfully setting or regenerating transaction PIN."""

    message: str = "Transaction PIN updated successfully"
    transaction_pin_set: bool = True


SetPinResponse = ResetPinResponse


class UserSummaryResponse(BaseModel):
    """User accounts overview summary schema."""

    model_config = ConfigDict(from_attributes=True)

    user_id: str
    full_name: str
    total_accounts: int
    total_balance_minor: int
    currency: str = "INR"

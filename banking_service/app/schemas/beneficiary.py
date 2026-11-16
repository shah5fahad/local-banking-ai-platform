"""Pydantic schemas for Beneficiary and Approval Challenge domain."""
from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CreateBeneficiaryRequest(BaseModel):
    """Request schema for creating a new beneficiary."""

    name: str = Field(..., min_length=2, max_length=255)
    nickname: str | None = Field(default=None, max_length=255)
    account_number: str
    ifsc: str
    bank_name: str = Field(..., min_length=2, max_length=255)

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


class BeneficiaryResponse(BaseModel):
    """Beneficiary detail response schema returning masked account number."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    name: str
    nickname: str | None
    account_number_masked: str
    last4: str
    ifsc: str
    bank_name: str
    verification_status: str
    approval_status: str
    status: str
    created_at: datetime


class UpdateBeneficiaryRequest(BaseModel):
    """Request schema for updating non-key beneficiary details."""

    name: str | None = None
    nickname: str | None = None


class VerifyBeneficiaryResponse(BaseModel):
    """Beneficiary verification response."""

    verification_status: str
    message: str


# ---------------------------------------------------------------------------
# Approval Challenge schemas
# ---------------------------------------------------------------------------

class ChallengeRequest(BaseModel):
    """Request to initiate an approval challenge for a sensitive operation."""

    action: str = Field(
        ...,
        description="Action type, e.g. BENEFICIARY_CREATE or BENEFICIARY_MODIFY",
    )
    payload_hash: str = Field(
        ...,
        description="SHA-256 hash of the normalized request payload being approved",
    )


class ChallengeResponse(BaseModel):
    """Response returned upon creating an approval challenge."""

    challenge_id: str
    action: str
    expires_in_seconds: int


class VerifyChallengeRequest(BaseModel):
    """Request to verify an approval challenge with customer PIN."""

    pin: str = Field(..., min_length=4, max_length=6, description="4-6 digit PIN")


class VerifyChallengeResponse(BaseModel):
    """Response returned upon successful challenge verification containing single-use token."""

    approval_token: str
    expires_in: int

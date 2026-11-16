"""Pydantic schemas for Fund Transfers."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class PrepareTransferRequest(BaseModel):
    """Payload to initiate/prepare a transfer."""

    source_account_id: str = Field(..., description="Source bank account UUID")
    beneficiary_id: str = Field(..., description="Beneficiary UUID")
    amount_minor: int = Field(..., gt=0, description="Transfer amount in minor units (paise)")
    currency: str = Field(default="INR", max_length=3)
    remark: Optional[str] = Field(default=None, max_length=255)
    channel: str = Field(default="IMPS", description="Payment channel: IMPS, NEFT, RTGS")


class PrepareTransferResponse(BaseModel):
    """Response returned upon preparing a transfer."""

    id: str
    reference: str
    status: str
    beneficiary: dict[str, Any]
    amount_minor: int
    fee_minor: int
    total_debit_minor: int
    currency: str
    available_balance_after_minor: int
    summary_hash: str
    expires_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TransferDetailResponse(BaseModel):
    """Full detail of a bank transaction / transfer."""

    id: str
    reference: str
    status: str
    source_account_id: Optional[str] = None
    beneficiary_id: Optional[str] = None
    amount_minor: int
    fee_minor: int
    total_debit_minor: int
    currency: str
    remark: Optional[str] = None
    channel: str
    summary_hash: Optional[str] = None
    failure_reason: Optional[str] = None
    created_at: datetime
    expires_at: Optional[datetime] = None
    executed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class TransferStatusResponse(BaseModel):
    """Lightweight status response for a transfer."""

    id: str
    reference: str
    status: str
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AuthorizeChallengeResponse(BaseModel):
    """Challenge issued for two-factor/PIN authorization."""

    challenge_id: str
    method: str
    expires_in_seconds: int

    model_config = ConfigDict(from_attributes=True)


class AuthorizeTransferRequest(BaseModel):
    """Authorization payload containing PIN or OTP."""

    challenge_id: str
    pin: Optional[str] = None
    otp: Optional[str] = None


class AuthorizeTransferResponse(BaseModel):
    """Response following authorization attempt."""

    authorization_id: str
    status: str

    model_config = ConfigDict(from_attributes=True)


class ExecuteTransferRequest(BaseModel):
    """Payload to execute an authorized transfer."""

    authorization_id: str
    summary_hash: str


class LimitsResponse(BaseModel):
    """User transfer limit overview."""

    per_transaction_limit_minor: int
    daily_limit_minor: int
    daily_used_minor: int
    daily_remaining_minor: int
    currency: str = "INR"

    model_config = ConfigDict(from_attributes=True)

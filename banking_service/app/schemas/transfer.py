"""Pydantic schemas for Fund Transfers."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, computed_field


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

    @computed_field  # type: ignore[prop-decorator]
    @property
    def amount(self) -> float:
        """Amount converted to rupees."""
        return round(self.amount_minor / 100.0, 2)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def amount_rupees(self) -> float:
        """Amount in rupees."""
        return round(self.amount_minor / 100.0, 2)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def amount_formatted(self) -> str:
        """Formatted amount string in INR (e.g. ₹5,000.00)."""
        return f"₹{self.amount_minor / 100.0:,.2f}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def fee_rupees(self) -> float:
        """Fee in rupees."""
        return round(self.fee_minor / 100.0, 2)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_debit(self) -> float:
        """Total debit in rupees."""
        return round(self.total_debit_minor / 100.0, 2)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_debit_rupees(self) -> float:
        """Total debit in rupees."""
        return round(self.total_debit_minor / 100.0, 2)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_debit_formatted(self) -> str:
        """Formatted total debit string in INR (e.g. ₹5,000.00)."""
        return f"₹{self.total_debit_minor / 100.0:,.2f}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def available_balance_after_rupees(self) -> float:
        """Available balance after transfer in rupees."""
        return round(self.available_balance_after_minor / 100.0, 2)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def available_balance_after_formatted(self) -> str:
        """Formatted available balance after transfer string in INR."""
        return f"₹{self.available_balance_after_minor / 100.0:,.2f}"


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

    @computed_field  # type: ignore[prop-decorator]
    @property
    def amount(self) -> float:
        """Amount converted to rupees."""
        return round(self.amount_minor / 100.0, 2)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def amount_rupees(self) -> float:
        """Amount in rupees."""
        return round(self.amount_minor / 100.0, 2)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def amount_formatted(self) -> str:
        """Formatted amount string in INR (e.g. ₹5,000.00)."""
        return f"₹{self.amount_minor / 100.0:,.2f}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def fee_rupees(self) -> float:
        """Fee in rupees."""
        return round(self.fee_minor / 100.0, 2)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_debit(self) -> float:
        """Total debit in rupees."""
        return round(self.total_debit_minor / 100.0, 2)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_debit_rupees(self) -> float:
        """Total debit in rupees."""
        return round(self.total_debit_minor / 100.0, 2)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_debit_formatted(self) -> str:
        """Formatted total debit string in INR (e.g. ₹5,000.00)."""
        return f"₹{self.total_debit_minor / 100.0:,.2f}"


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

    @computed_field  # type: ignore[prop-decorator]
    @property
    def per_transaction_limit_rupees(self) -> float:
        """Per-transaction limit in rupees."""
        return round(self.per_transaction_limit_minor / 100.0, 2)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def daily_limit_rupees(self) -> float:
        """Daily limit in rupees."""
        return round(self.daily_limit_minor / 100.0, 2)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def daily_used_rupees(self) -> float:
        """Daily used in rupees."""
        return round(self.daily_used_minor / 100.0, 2)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def daily_remaining_rupees(self) -> float:
        """Daily remaining in rupees."""
        return round(self.daily_remaining_minor / 100.0, 2)

"""Pydantic schemas for Admin operations and System Configuration."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class AdminStatsResponse(BaseModel):
    """Aggregate statistics for admin dashboard."""

    total_users: int
    active_users: int
    total_accounts: int
    total_transactions: int
    total_loans_submitted: int
    total_loan_amount_minor: int


class AdminUserResponse(BaseModel):
    """User representation for admin viewers."""

    id: str
    email: str
    phone: str
    full_name: str
    is_active: bool
    failed_login_count: int
    locked_until: Optional[datetime] = None
    roles: list[str] = []
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UpdateUserStatusRequest(BaseModel):
    """Payload to activate or deactivate a user."""

    is_active: bool


class UpdateUserRolesRequest(BaseModel):
    """Payload to assign roles to a user."""

    roles: list[str] = Field(..., min_length=1)


class AdminTransactionResponse(BaseModel):
    """Transaction representation for admin overview."""

    id: str
    reference: str
    user_id: str
    type: str
    amount_minor: int
    fee_minor: int
    total_debit_minor: int
    currency: str
    status: str
    channel: str
    source_account_masked: Optional[str] = None
    beneficiary_id: Optional[str] = None
    failure_reason: Optional[str] = None
    created_at: datetime
    executed_at: Optional[datetime] = None


class AdminLoanResponse(BaseModel):
    """Loan application view for admin."""

    id: str
    reference: str
    user_id: str
    loan_type: str
    amount_minor: int
    tenure_months: int
    rate_bps: int
    employment_type: str
    employer: str
    monthly_income_minor: int
    status: str
    decision_reason: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ConfigResponse(BaseModel):
    """Banking system runtime configuration response."""

    transfer_per_txn_limit_minor: int
    transfer_daily_limit_minor: int
    transfer_approval_expiry_seconds: int
    duplicate_window_seconds: int
    txn_auth_method: str
    txn_auth_max_attempts: int


class UpdateConfigRequest(BaseModel):
    """Payload to update runtime limits and configuration."""

    transfer_per_txn_limit_minor: Optional[int] = Field(None, gt=0)
    transfer_daily_limit_minor: Optional[int] = Field(None, gt=0)
    transfer_approval_expiry_seconds: Optional[int] = Field(None, gt=0)
    duplicate_window_seconds: Optional[int] = Field(None, gt=0)
    txn_auth_method: Optional[str] = None
    txn_auth_max_attempts: Optional[int] = Field(None, ge=1)

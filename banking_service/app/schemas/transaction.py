"""Pydantic schemas for Transaction history and lookup."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class TransactionResponse(BaseModel):
    """Transaction detail representation."""

    id: str
    reference: str
    type: str
    amount_minor: int
    fee_minor: int
    total_debit_minor: int
    currency: str
    status: str
    remark: Optional[str] = None
    channel: str
    source_account_id: Optional[str] = None
    beneficiary_id: Optional[str] = None
    failure_reason: Optional[str] = None
    created_at: datetime
    executed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class TransactionListResponse(BaseModel):
    """Paginated list of transactions."""

    items: list[TransactionResponse]
    total: int
    page: int
    page_size: int
    has_next: bool

    model_config = ConfigDict(from_attributes=True)

"""Pydantic schemas for Transaction history and lookup."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, computed_field


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

    @computed_field  # type: ignore[prop-decorator]
    @property
    def amount(self) -> float:
        """Amount converted to rupees (major currency unit)."""
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
        """Fee converted to rupees."""
        return round(self.fee_minor / 100.0, 2)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_debit(self) -> float:
        """Total debit converted to rupees."""
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


class TransactionListResponse(BaseModel):
    """Paginated list of transactions."""

    items: list[TransactionResponse]
    total: int
    page: int
    page_size: int
    has_next: bool

    model_config = ConfigDict(from_attributes=True)

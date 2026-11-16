"""Pydantic schemas for Human-in-the-Loop approvals and decisions."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class DecisionRequest(BaseModel):
    """User decision payload: confirm or reject pending action."""

    decision: Literal["CONFIRM", "REJECT"] = Field(
        ..., description="Human decision: CONFIRM or REJECT"
    )


class ResumeRequest(BaseModel):
    """Resume execution payload carrying the authorization ID from Banking API."""

    authorization_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Authorization ID from direct PIN/OTP auth",
    )
    summary_hash: str | None = Field(
        default=None,
        description="Optional summary_hash to verify against stored approval for tamper detection",
    )


class ApprovalResponse(BaseModel):
    """Details and status of a pending or past approval."""

    approval_id: str
    conversation_id: str
    workflow: str
    risk_level: str
    status: str
    summary: dict[str, Any]
    summary_hash: str
    banking_resource_id: str | None = None
    expires_at: str | None = None
    decided_at: str | None = None


class DecisionResponse(BaseModel):
    """Response returned upon submitting a CONFIRM/REJECT decision."""

    approval_id: str
    status: str
    decided_at: str | None = None
    requires_auth: bool = False
    workflow: str | None = None
    banking_resource_id: str | None = None
    response: str | None = None


class ResumeResponse(BaseModel):
    """Response returned after resuming execution with authorization credentials."""

    approval_id: str
    status: str
    authorization_id: str
    workflow: str | None = None
    response: str | None = None


class SweepResponse(BaseModel):
    """Response returned from running an approval expiry sweep."""

    swept_count: int
    swept_approvals: list[str] = Field(default_factory=list)
    details: list[dict[str, Any]] = Field(default_factory=list)


class PruneCheckpointsRequest(BaseModel):
    """Request payload for manual checkpoint pruning."""

    older_than_days: int = Field(default=7, ge=0, description="Age threshold in days")


class PruneCheckpointsResponse(BaseModel):
    """Response returned from checkpoint pruning."""

    pruned_metadata_count: int
    pruned_checkpoints_count: int
    pruned_blobs_count: int
    pruned_writes_count: int
    message: str

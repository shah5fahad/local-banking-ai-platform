"""Pydantic schemas for Audit Log viewers."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class AuditLogResponse(BaseModel):
    """Audit log entry representation."""

    id: str
    ts: datetime
    actor_user_id: Optional[str] = None
    actor_type: str
    service: str
    action: str
    resource_type: str
    resource_id: Optional[str] = None
    outcome: str
    request_id: Optional[str] = None
    ip: Optional[str] = None
    details_json: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

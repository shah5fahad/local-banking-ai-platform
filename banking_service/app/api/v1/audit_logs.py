"""Audit Logs API router for compliance, auditor, and admin security monitoring."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query

from app.core.deps import DbSession, RequireAdminOrAuditor
from app.core.errors import NotFoundError
from app.repositories.audit_repository import AuditRepository
from app.schemas.audit_log import AuditLogResponse

router = APIRouter(prefix="/audit-logs", tags=["audit-logs"])


@router.get("", response_model=list[AuditLogResponse], summary="List audit logs")
def list_audit_logs(
    admin_or_auditor: RequireAdminOrAuditor,
    db: DbSession,
    actor: Optional[str] = Query(None, description="Filter by actor user ID"),
    action: Optional[str] = Query(None, description="Filter by action name"),
    resource_type: Optional[str] = Query(None, description="Filter by resource type"),
    outcome: Optional[str] = Query(None, description="Filter by outcome (SUCCESS, FAILURE)"),
    from_date: Optional[datetime] = Query(None, description="Start timestamp"),
    to_date: Optional[datetime] = Query(None, description="End timestamp"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> list[AuditLogResponse]:
    """Search and filter the immutable audit log trail."""
    repo = AuditRepository(db)
    filters = {
        "actor": actor,
        "action": action,
        "resource_type": resource_type,
        "outcome": outcome,
        "from_date": from_date,
        "to_date": to_date,
    }
    logs, _ = repo.list(filters, page=page, page_size=page_size)
    return [AuditLogResponse.model_validate(log) for log in logs]


@router.get("/{id}", response_model=AuditLogResponse, summary="Get audit log by ID")
def get_audit_log(
    id: str,
    admin_or_auditor: RequireAdminOrAuditor,
    db: DbSession,
) -> AuditLogResponse:
    """Fetch specific audit log entry."""
    repo = AuditRepository(db)
    log = repo.get_by_id(id)
    if not log:
        raise NotFoundError("Audit log", id)
    return AuditLogResponse.model_validate(log)

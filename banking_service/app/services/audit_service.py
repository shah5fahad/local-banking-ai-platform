"""Audit service for logging critical actions across all banking subsystems."""
from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.repositories.audit_repository import AuditRepository


class AuditService:
    """Service helper to record audit logs."""

    @staticmethod
    def _mask_details(details: dict[str, Any]) -> dict[str, Any]:
        """Mask sensitive keys in audit log details."""
        sensitive_keys = {"password", "pin", "token", "account_number", "secret", "cvv"}
        masked: dict[str, Any] = {}
        for k, v in details.items():
            if any(s in k.lower() for s in sensitive_keys):
                masked[k] = "[MASKED]"
            elif isinstance(v, dict):
                masked[k] = AuditService._mask_details(v)
            else:
                masked[k] = v
        return masked

    @staticmethod
    def log(
        db: Session,
        action: str,
        actor_user_id: Optional[str] = None,
        actor_type: str = "SYSTEM",
        resource_type: str = "SYSTEM",
        resource_id: Optional[str] = None,
        outcome: str = "SUCCESS",
        request_id: Optional[str] = None,
        ip: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        service: str = "banking",
    ) -> AuditLog:
        """Create and commit an audit log entry."""
        repo = AuditRepository(db)
        masked_details = AuditService._mask_details(details) if details else None
        details_str = json.dumps(masked_details) if masked_details is not None else None
        return repo.create(
            actor_user_id=actor_user_id,
            actor_type=actor_type,
            service=service,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=outcome,
            request_id=request_id,
            ip=ip,
            details_json=details_str,
        )


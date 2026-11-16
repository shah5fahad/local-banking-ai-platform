"""Audit repository for storing and querying immutable audit logs."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


class AuditRepository:
    """Repository handling append-only audit trail."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        actor_user_id: Optional[str],
        actor_type: str,
        service: str,
        action: str,
        resource_type: str,
        resource_id: Optional[str],
        outcome: str = "SUCCESS",
        request_id: Optional[str] = None,
        ip: Optional[str] = None,
        details_json: Optional[str] = None,
    ) -> AuditLog:
        """Create and persist an append-only audit log entry."""
        latest = (
            self.session.query(AuditLog)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .first()
        )
        prev_hash = latest.hash if latest else None
        entry_id = str(uuid.uuid4())
        hash_payload = f"{prev_hash or ''}:{action}:{outcome}:{actor_user_id or ''}:{details_json or ''}:{entry_id}"
        entry_hash = hashlib.sha256(hash_payload.encode("utf-8")).hexdigest()

        audit = AuditLog(
            id=entry_id,
            actor_user_id=actor_user_id,
            actor_type=actor_type,
            service=service,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=outcome,
            request_id=request_id,
            ip=ip,
            details_json=details_json,
            prev_hash=prev_hash,
            hash=entry_hash,
        )
        self.session.add(audit)
        self.session.flush()
        return audit

    def get_by_id(self, id: str) -> AuditLog | None:
        """Fetch audit log by ID."""
        stmt = select(AuditLog).where(AuditLog.id == id)
        return self.session.scalar(stmt)

    def list(
        self,
        filters: dict[str, Any],
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[AuditLog], int]:
        """Query audit logs with filtering and pagination."""
        stmt = select(AuditLog)
        count_stmt = select(func.count(AuditLog.id))

        if "actor" in filters and filters["actor"]:
            stmt = stmt.where(AuditLog.actor_user_id == filters["actor"])
            count_stmt = count_stmt.where(AuditLog.actor_user_id == filters["actor"])

        if "action" in filters and filters["action"]:
            stmt = stmt.where(AuditLog.action == filters["action"])
            count_stmt = count_stmt.where(AuditLog.action == filters["action"])

        if "resource_type" in filters and filters["resource_type"]:
            stmt = stmt.where(AuditLog.resource_type == filters["resource_type"])
            count_stmt = count_stmt.where(AuditLog.resource_type == filters["resource_type"])

        if "outcome" in filters and filters["outcome"]:
            stmt = stmt.where(AuditLog.outcome == filters["outcome"])
            count_stmt = count_stmt.where(AuditLog.outcome == filters["outcome"])

        if "from_date" in filters and filters["from_date"]:
            stmt = stmt.where(AuditLog.ts >= filters["from_date"])
            count_stmt = count_stmt.where(AuditLog.ts >= filters["from_date"])

        if "to_date" in filters and filters["to_date"]:
            stmt = stmt.where(AuditLog.ts <= filters["to_date"])
            count_stmt = count_stmt.where(AuditLog.ts <= filters["to_date"])

        total = self.session.scalar(count_stmt) or 0
        offset = (max(page, 1) - 1) * page_size
        items = list(
            self.session.scalars(
                stmt.order_by(AuditLog.ts.desc()).offset(offset).limit(page_size)
            ).all()
        )
        return items, total

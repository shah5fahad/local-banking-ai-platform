"""ApprovalService: manage HITL pending approvals, decisions, and resume flows."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import AISettings, get_settings
from app.core.errors import ConflictError, NotFoundError
from app.core.security import create_service_token_for_user
from app.integrations.banking_client import BankingClient
from app.models.approval import (
    DEFAULT_APPROVAL_TTL_SECONDS,
    ApprovalStatus,
    PendingApproval,
    RiskLevel,
    WorkflowType,
)
from app.models.chat import ChatUserReference, Conversation
from app.models.checkpoint import WorkflowCheckpointMetadata

logger = logging.getLogger(__name__)


class ApprovalService:
    """Service managing human-in-the-loop approvals, timeouts, decisions, and resumptions."""

    def __init__(self, db: Session, settings: AISettings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

    def supersede_pending_approvals(
        self,
        conversation_id: str,
        workflow_type: str | None = None,
        raw_token: str | None = None,
        exclude_banking_resource_id: str | None = None,
    ) -> list[PendingApproval]:
        """Cancel and supersede existing active approvals for this conversation.

        Enforces the rule: at most one active approval per workflow type per conversation.
        Cancels any associated banking transfer drafts and marks status SUPERSEDED.
        """
        stmt = (
            select(PendingApproval)
            .where(PendingApproval.conversation_id == conversation_id)
            .where(
                PendingApproval.status.in_([
                    ApprovalStatus.PENDING.value,
                    ApprovalStatus.CONFIRMED.value,
                    ApprovalStatus.AUTH_REQUIRED.value,
                ])
            )
        )
        if workflow_type:
            stmt = stmt.where(PendingApproval.workflow_type == workflow_type)
        if exclude_banking_resource_id:
            stmt = stmt.where(PendingApproval.banking_resource_id != exclude_banking_resource_id)

        active_approvals = list(self.db.execute(stmt).scalars().all())
        if not active_approvals:
            return []

        now = datetime.now(UTC)

        # Retrieve banking_user_id for draft cancellation if raw_token not provided
        banking_user_id: str | None = None
        user_stmt = (
            select(ChatUserReference.banking_user_id)
            .join(Conversation, Conversation.user_ref_id == ChatUserReference.id)
            .where(Conversation.id == conversation_id)
        )
        banking_user_id = self.db.execute(user_stmt).scalar_one_or_none()

        cancellation_token = raw_token
        if not cancellation_token and banking_user_id:
            try:
                cancellation_token = create_service_token_for_user(banking_user_id, self.settings)
            except Exception as exc:
                logger.debug("Could not generate service token for supersede cancellation: %s", exc)

        for approval in active_approvals:
            if approval.is_expired:
                approval.status = ApprovalStatus.EXPIRED.value
                approval.decided_at = now
                chk = self.db.get(WorkflowCheckpointMetadata, approval.thread_id)
                if chk:
                    chk.status = "EXPIRED"
                continue

            # Cancel draft at banking service if applicable
            if (
                approval.banking_resource_id
                and approval.workflow_type == WorkflowType.TRANSFER.value
                and cancellation_token
            ):
                try:
                    client = BankingClient(settings=self.settings, access_token=cancellation_token)
                    client.cancel_transfer(approval.banking_resource_id)
                    logger.info(
                        "Cancelled superseded banking transfer draft %s for approval %s",
                        approval.banking_resource_id,
                        approval.id,
                    )
                except Exception as exc:
                    logger.warning(
                        "Failed to cancel superseded banking transfer draft '%s': %s",
                        approval.banking_resource_id,
                        exc,
                    )

            approval.status = ApprovalStatus.SUPERSEDED.value
            approval.decided_at = now

            # Update checkpoint metadata
            chk = self.db.get(WorkflowCheckpointMetadata, approval.thread_id)
            if chk:
                chk.status = "SUPERSEDED"

        self.db.commit()
        for app in active_approvals:
            self.db.refresh(app)

        logger.info(
            "Superseded %d approval(s) in conversation %s workflow=%s",
            len(active_approvals),
            conversation_id,
            workflow_type,
        )
        return active_approvals

    def get_active_approval_for_conversation(
        self,
        conversation_id: str,
        workflow_type: str | None = None,
        banking_user_id: str | None = None,
    ) -> PendingApproval | None:
        """Get the current active PendingApproval for a conversation, expiring if overdue."""
        stmt = (
            select(PendingApproval)
            .join(Conversation, PendingApproval.conversation_id == Conversation.id)
            .join(ChatUserReference, Conversation.user_ref_id == ChatUserReference.id)
            .where(PendingApproval.conversation_id == conversation_id)
            .where(
                PendingApproval.status.in_([
                    ApprovalStatus.PENDING.value,
                    ApprovalStatus.CONFIRMED.value,
                    ApprovalStatus.AUTH_REQUIRED.value,
                ])
            )
        )
        if workflow_type:
            stmt = stmt.where(PendingApproval.workflow_type == workflow_type)
        if banking_user_id:
            stmt = stmt.where(ChatUserReference.banking_user_id == banking_user_id)
        stmt = stmt.order_by(PendingApproval.created_at.desc())

        approvals = list(self.db.execute(stmt).scalars().all())
        now = datetime.now(UTC)
        for approval in approvals:
            if approval.is_expired:
                approval.status = ApprovalStatus.EXPIRED.value
                approval.decided_at = now
                self.db.commit()
                self.db.refresh(approval)
            else:
                return approval
        return None

    def create_approval(
        self,
        conversation_id: str,
        thread_id: str,
        workflow_type: str,
        risk_level: str | None = None,
        summary_masked: dict[str, Any] | None = None,
        summary_hash: str | None = None,
        banking_resource_id: str | None = None,
        ttl_seconds: int | None = None,
        raw_token: str | None = None,
        auto_supersede: bool = True,
    ) -> PendingApproval:
        """Create and persist a new PendingApproval record, superseding prior active ones."""
        if auto_supersede:
            self.supersede_pending_approvals(
                conversation_id=conversation_id,
                workflow_type=workflow_type,
                raw_token=raw_token,
                exclude_banking_resource_id=banking_resource_id,
            )

        summary = summary_masked or {}
        summary_json = json.dumps(summary, sort_keys=True)

        if not summary_hash:
            summary_hash = hashlib.sha256(summary_json.encode("utf-8")).hexdigest()

        if risk_level is None:
            if workflow_type in (
                WorkflowType.TRANSFER.value,
                WorkflowType.CARD_PAYMENT.value,
                WorkflowType.LOAN.value,
            ):
                risk_level = RiskLevel.FINANCIAL.value
            else:
                risk_level = RiskLevel.SENSITIVE.value

        if ttl_seconds is None:
            ttl_seconds = DEFAULT_APPROVAL_TTL_SECONDS.get(workflow_type, 300)

        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=ttl_seconds)

        approval = PendingApproval(
            conversation_id=conversation_id,
            thread_id=thread_id,
            workflow_type=workflow_type,
            risk_level=risk_level,
            summary_masked_json=summary_json,
            summary_hash=summary_hash,
            banking_resource_id=banking_resource_id,
            status=ApprovalStatus.PENDING.value,
            expires_at=expires_at,
            created_at=now,
        )

        self.db.add(approval)

        # Upsert WorkflowCheckpointMetadata
        chk = self.db.get(WorkflowCheckpointMetadata, thread_id)
        if not chk:
            chk = WorkflowCheckpointMetadata(
                thread_id=thread_id,
                conversation_id=conversation_id,
                last_node="approval_gate",
                status="ACTIVE",
                expires_at=expires_at,
            )
            self.db.add(chk)
        else:
            chk.status = "ACTIVE"
            chk.expires_at = expires_at
            chk.last_node = "approval_gate"
            chk.cleaned_at = None

        self.db.commit()
        self.db.refresh(approval)
        logger.info(
            "Created PendingApproval id=%s workflow=%s conversation=%s expires_at=%s",
            approval.id,
            workflow_type,
            conversation_id,
            expires_at.isoformat(),
        )
        return approval

    def get_approval(
        self,
        approval_id: str,
        banking_user_id: str | None = None,
    ) -> PendingApproval:
        """Retrieve a PendingApproval with strict user ownership validation."""
        stmt = (
            select(PendingApproval)
            .join(Conversation, PendingApproval.conversation_id == Conversation.id)
            .join(ChatUserReference, Conversation.user_ref_id == ChatUserReference.id)
            .where(PendingApproval.id == approval_id)
        )

        if banking_user_id:
            stmt = stmt.where(ChatUserReference.banking_user_id == banking_user_id)

        approval = self.db.execute(stmt).scalar_one_or_none()
        if not approval:
            raise NotFoundError("Approval", approval_id)

        # Check and update expiry if applicable
        if (
            approval.is_expired
            and approval.status in (
                ApprovalStatus.PENDING.value,
                ApprovalStatus.AUTH_REQUIRED.value,
                ApprovalStatus.CONFIRMED.value,
            )
        ):
            logger.info("Approval id=%s expired at %s", approval.id, approval.expires_at)
            approval.status = ApprovalStatus.EXPIRED.value
            self.db.commit()
            self.db.refresh(approval)

        return approval

    def decide_approval(
        self,
        approval_id: str,
        decision: str,
        banking_user_id: str,
        raw_token: str | None = None,
    ) -> dict[str, Any]:
        """Process CONFIRM or REJECT decision for a pending approval."""
        approval = self.get_approval(approval_id, banking_user_id=banking_user_id)

        if approval.status == ApprovalStatus.SUPERSEDED.value:
            raise ConflictError("Approval request has been superseded by a newer request")

        if approval.is_expired or approval.status == ApprovalStatus.EXPIRED.value:
            raise ConflictError("Approval request has expired")

        norm_decision = decision.strip().upper()
        if norm_decision not in ("CONFIRM", "REJECT"):
            raise ConflictError(f"Invalid decision '{decision}'. Must be CONFIRM or REJECT")

        now = datetime.now(UTC)

        if norm_decision == "REJECT":
            # Idempotent replay for already rejected
            if approval.status == ApprovalStatus.REJECTED.value:
                return {
                    "approval_id": approval.id,
                    "status": approval.status,
                    "decided_at": approval.decided_at.isoformat() if approval.decided_at else None,
                    "workflow": approval.workflow_type,
                    "banking_resource_id": approval.banking_resource_id,
                }

            if approval.status == ApprovalStatus.EXECUTED.value:
                raise ConflictError(
                    "Cannot reject approval in state 'EXECUTED': Transaction has already been executed."
                )

            if approval.status not in (
                ApprovalStatus.PENDING.value,
                ApprovalStatus.AUTH_REQUIRED.value,
            ):
                raise ConflictError(
                    f"Cannot reject approval in state '{approval.status}'"
                )

            # Cancel draft at banking service if applicable
            if (
                approval.banking_resource_id
                and raw_token
                and approval.workflow_type == WorkflowType.TRANSFER.value
            ):
                try:
                    client = BankingClient(settings=self.settings, access_token=raw_token)
                    client.cancel_transfer(approval.banking_resource_id)
                    logger.info("Cancelled banking draft %s", approval.banking_resource_id)
                except Exception as exc:
                    logger.warning(
                        "Failed to cancel banking transfer draft '%s': %s",
                        approval.banking_resource_id,
                        exc,
                    )

            approval.status = ApprovalStatus.REJECTED.value
            approval.decided_at = now
            chk = self.db.get(WorkflowCheckpointMetadata, approval.thread_id)
            if chk:
                chk.status = "REJECTED"
            self.db.commit()
            self.db.refresh(approval)

            # Resume graph checkpoint with REJECT Command
            try:
                from app.agents.graph import resume_graph

                resume_graph(
                    thread_id=approval.thread_id,
                    resume_payload={"decision": "REJECT", "approval_id": approval.id, "cancelled": True},
                    access_token=raw_token,
                )
            except Exception as exc:
                logger.debug("Graph resume on reject: %s", exc)

            return {
                "approval_id": approval.id,
                "status": approval.status,
                "decided_at": approval.decided_at.isoformat() if approval.decided_at else None,
                "workflow": approval.workflow_type,
                "banking_resource_id": approval.banking_resource_id,
            }

        # norm_decision == "CONFIRM"
        if approval.status in (
            ApprovalStatus.CONFIRMED.value,
            ApprovalStatus.AUTH_REQUIRED.value,
            ApprovalStatus.AUTHENTICATED.value,
            ApprovalStatus.EXECUTED.value,
        ):
            # Idempotent replay
            requires_auth = approval.workflow_type in (
                WorkflowType.TRANSFER.value,
                WorkflowType.CARD_PAYMENT.value,
                WorkflowType.BENEFICIARY.value,
            )
            return {
                "approval_id": approval.id,
                "status": approval.status,
                "decided_at": approval.decided_at.isoformat() if approval.decided_at else None,
                "requires_auth": requires_auth,
                "workflow": approval.workflow_type,
                "banking_resource_id": approval.banking_resource_id,
            }

        if approval.status != ApprovalStatus.PENDING.value:
            raise ConflictError(f"Cannot confirm approval in state '{approval.status}'")

        requires_auth = approval.workflow_type in (
            WorkflowType.TRANSFER.value,
            WorkflowType.CARD_PAYMENT.value,
            WorkflowType.BENEFICIARY.value,
        )
        approval.decided_at = now

        if requires_auth:
            approval.status = ApprovalStatus.AUTH_REQUIRED.value
            self.db.commit()
            self.db.refresh(approval)

            # Resume graph to transition from CONFIRM interrupt to AUTH_REQUIRED interrupt
            try:
                from app.agents.graph import resume_graph

                resume_graph(
                    thread_id=approval.thread_id,
                    resume_payload={"decision": "CONFIRM", "approval_id": approval.id},
                    access_token=raw_token,
                )
            except Exception as exc:
                logger.debug("Graph resume paused at auth_required: %s", exc)

            return {
                "approval_id": approval.id,
                "status": approval.status,
                "decided_at": approval.decided_at.isoformat() if approval.decided_at else None,
                "requires_auth": True,
                "workflow": approval.workflow_type,
                "banking_resource_id": approval.banking_resource_id,
            }

        # Workflow does not require secondary authentication (e.g. loan application)
        approval.status = ApprovalStatus.CONFIRMED.value
        self.db.commit()
        self.db.refresh(approval)

        exec_res: dict[str, Any] | None = None
        try:
            from app.agents.graph import resume_graph

            exec_res = resume_graph(
                thread_id=approval.thread_id,
                resume_payload={"decision": "CONFIRM", "approval_id": approval.id},
                access_token=raw_token,
            )
            approval.status = ApprovalStatus.EXECUTED.value
            chk = self.db.get(WorkflowCheckpointMetadata, approval.thread_id)
            if chk:
                chk.status = "EXECUTED"
            self.db.commit()
            self.db.refresh(approval)
        except Exception as exc:
            logger.warning("Graph resume execution error: %s", exc)

        return {
            "approval_id": approval.id,
            "status": approval.status,
            "decided_at": approval.decided_at.isoformat() if approval.decided_at else None,
            "requires_auth": False,
            "workflow": approval.workflow_type,
            "banking_resource_id": approval.banking_resource_id,
            "response": exec_res.get("response") if isinstance(exec_res, dict) else None,
        }

    def resume_approval(
        self,
        approval_id: str,
        authorization_id: str,
        banking_user_id: str,
        raw_token: str,
        summary_hash: str | None = None,
    ) -> dict[str, Any]:
        """Resume transaction execution after user completed PIN/OTP direct at banking."""
        approval = self.get_approval(approval_id, banking_user_id=banking_user_id)

        if approval.status == ApprovalStatus.SUPERSEDED.value:
            raise ConflictError("Approval request has been superseded by a newer request")

        if approval.is_expired or approval.status == ApprovalStatus.EXPIRED.value:
            raise ConflictError("Approval request has expired")

        if summary_hash and approval.summary_hash != summary_hash:
            raise ConflictError("Summary hash mismatch: transaction details have been tampered with")

        # Idempotent replay if already authenticated or executed
        if approval.status in (
            ApprovalStatus.AUTHENTICATED.value,
            ApprovalStatus.EXECUTED.value,
        ):
            return {
                "approval_id": approval.id,
                "status": approval.status,
                "authorization_id": authorization_id,
                "workflow": approval.workflow_type,
            }

        if approval.status == ApprovalStatus.PENDING.value:
            raise ConflictError("Approval requires confirmation before authorization")

        if approval.status in (
            ApprovalStatus.REJECTED.value,
            ApprovalStatus.CANCELLED.value,
        ):
            raise ConflictError(f"Cannot resume approval in state '{approval.status}'")

        if approval.status not in (
            ApprovalStatus.AUTH_REQUIRED.value,
            ApprovalStatus.CONFIRMED.value,
        ):
            raise ConflictError(f"Cannot resume approval in state '{approval.status}'")

        approval.status = ApprovalStatus.AUTHENTICATED.value
        self.db.commit()
        self.db.refresh(approval)

        exec_res: dict[str, Any] | None = None
        try:
            from app.agents.graph import resume_graph

            exec_res = resume_graph(
                thread_id=approval.thread_id,
                resume_payload={"authorization_id": authorization_id, "approval_id": approval.id},
                access_token=raw_token,
            )
            approval.status = ApprovalStatus.EXECUTED.value
            chk = self.db.get(WorkflowCheckpointMetadata, approval.thread_id)
            if chk:
                chk.status = "EXECUTED"
            self.db.commit()
            self.db.refresh(approval)
        except Exception as exc:
            logger.warning("Graph resume after auth failed: %s", exc)

        # Record assistant response to chat message if generated
        if isinstance(exec_res, dict) and exec_res.get("response"):
            try:
                from app.repositories.conversation_repository import ConversationRepository

                repo = ConversationRepository(self.db)
                repo.add_message(
                    conversation_id=approval.conversation_id,
                    role="assistant",
                    content_masked=exec_res["response"],
                )
                self.db.commit()
            except Exception as exc:
                logger.warning("Could not persist assistant execution response: %s", exc)

        return {
            "approval_id": approval.id,
            "status": approval.status,
            "authorization_id": authorization_id,
            "workflow": approval.workflow_type,
            "response": exec_res.get("response") if isinstance(exec_res, dict) else None,
        }
